#!/usr/bin/python
# coding: utf-8

########################

import xbmc
import xbmcvfs
import sqlite3
import json
import time
import os
from threading import Thread, Lock
from queue import Queue

########################

ADDON_DATA_PATH = xbmcvfs.translatePath('special://profile/addon_data/script.embuary.info/')
DB_PATH = os.path.join(ADDON_DATA_PATH, 'cast_cache.db')
CACHE_TTL_CAST = 7 * 24 * 60 * 60  # 7 dias em segundos
CACHE_TTL_IMDB_MAP = 30 * 24 * 60 * 60  # 30 dias (conversão IMDB→TMDB raramente muda)

########################

class CastCacheManager:
    """
    Gerenciador de cache SQLite para dados de cast com background worker.
    
    Features:
    - Cache persistente em SQLite
    - Background worker que salva a cada 0.5s
    - Conversão IMDB→TMDB com cache
    - Thread-safe
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(CastCacheManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Inicializa o cache manager"""
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.write_queue = Queue()
        self.db_lock = Lock()
        self.worker_running = False
        
        # Cria diretório se não existir
        if not os.path.exists(ADDON_DATA_PATH):
            os.makedirs(ADDON_DATA_PATH)
        
        # Inicializa banco de dados
        self._init_database()
        
        # Inicia background worker
        self._start_worker()
        
        xbmc.log('[script.embuary.info] CastCacheManager initialized', xbmc.LOGINFO)
    
    def _init_database(self):
        """Cria tabelas se não existirem"""
        with self.db_lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Tabela de cache de cast
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cast_cache (
                    cache_key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    ttl INTEGER DEFAULT %d
                )
            ''' % CACHE_TTL_CAST)
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cast_timestamp ON cast_cache(timestamp)')
            
            # Tabela de conversão IMDB → TMDB
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS imdb_tmdb_map (
                    imdb_id TEXT PRIMARY KEY,
                    tmdb_id TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            ''')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_map_timestamp ON imdb_tmdb_map(timestamp)')
            
            conn.commit()
            conn.close()
        
        # Limpa entradas expiradas
        self.cleanup_expired()
    
    def _start_worker(self):
        """Inicia background worker que salva a cada 0.5s"""
        self.worker_running = True
        worker_thread = Thread(target=self._worker_loop, name='CastCacheWorker')
        worker_thread.daemon = True
        worker_thread.start()
    
    def _worker_loop(self):
        """Loop do worker que processa fila a cada 0.5s"""
        while self.worker_running:
            try:
                time.sleep(0.5)  # Verifica a cada 0.5s
                self._flush_queue()
            except Exception as e:
                xbmc.log('[script.embuary.info] Cache worker error: %s' % str(e), xbmc.LOGERROR)
    
    def _flush_queue(self):
        """Processa todos os itens na fila de escrita"""
        if self.write_queue.empty():
            return
        
        items_to_write = []
        while not self.write_queue.empty():
            try:
                items_to_write.append(self.write_queue.get_nowait())
            except:
                break
        
        if not items_to_write:
            return
        
        # Escreve em batch para melhor performance
        with self.db_lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            for item in items_to_write:
                table = item['table']
                data = item['data']
                
                if table == 'cast_cache':
                    cursor.execute('''
                        INSERT OR REPLACE INTO cast_cache (cache_key, data, timestamp, ttl)
                        VALUES (?, ?, ?, ?)
                    ''', (data['key'], data['value'], data['timestamp'], data['ttl']))
                
                elif table == 'imdb_tmdb_map':
                    cursor.execute('''
                        INSERT OR REPLACE INTO imdb_tmdb_map (imdb_id, tmdb_id, media_type, timestamp)
                        VALUES (?, ?, ?, ?)
                    ''', (data['imdb_id'], data['tmdb_id'], data['media_type'], data['timestamp']))
            
            conn.commit()
            conn.close()
        
        xbmc.log('[script.embuary.info] Flushed %d cache items' % len(items_to_write), xbmc.LOGDEBUG)
    
    def get(self, key):
        """
        Busca dados do cache.
        
        Args:
            key: Chave do cache
            
        Returns:
            Dados em formato dict ou None se não encontrado/expirado
        """
        with self.db_lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT data, timestamp, ttl FROM cast_cache WHERE cache_key = ?
            ''', (key,))
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return None
            
            data, timestamp, ttl = row
            
            # Verifica se expirou
            if time.time() - timestamp > ttl:
                # Remove entrada expirada
                self._delete_expired_cast(key)
                return None
            
            try:
                return json.loads(data)
            except:
                return None
    
    def set(self, key, data, ttl=CACHE_TTL_CAST):
        """
        Salva dados no cache (adiciona à fila).
        
        Args:
            key: Chave do cache
            data: Dados para salvar (será convertido para JSON)
            ttl: Time to live em segundos (padrão: 7 dias)
        """
        try:
            json_data = json.dumps(data, ensure_ascii=False)
            
            self.write_queue.put({
                'table': 'cast_cache',
                'data': {
                    'key': key,
                    'value': json_data,
                    'timestamp': int(time.time()),
                    'ttl': ttl
                }
            })
        except Exception as e:
            xbmc.log('[script.embuary.info] Cache set error: %s' % str(e), xbmc.LOGERROR)
    
    def get_tmdb_from_imdb(self, imdb_id):
        """
        Busca TMDB ID a partir do IMDB ID no cache.
        
        Args:
            imdb_id: IMDB ID (ex: tt1234567)
            
        Returns:
            Tuple (tmdb_id, media_type) ou (None, None) se não encontrado
        """
        with self.db_lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT tmdb_id, media_type, timestamp FROM imdb_tmdb_map WHERE imdb_id = ?
            ''', (imdb_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return None, None
            
            tmdb_id, media_type, timestamp = row
            
            # Verifica se expirou (30 dias)
            if time.time() - timestamp > CACHE_TTL_IMDB_MAP:
                return None, None
            
            return tmdb_id, media_type
    
    def set_imdb_tmdb_map(self, imdb_id, tmdb_id, media_type):
        """
        Salva conversão IMDB→TMDB no cache.
        
        Args:
            imdb_id: IMDB ID
            tmdb_id: TMDB ID
            media_type: Tipo de mídia ('movie' ou 'tv')
        """
        self.write_queue.put({
            'table': 'imdb_tmdb_map',
            'data': {
                'imdb_id': imdb_id,
                'tmdb_id': str(tmdb_id),
                'media_type': media_type,
                'timestamp': int(time.time())
            }
        })
    
    def _delete_expired_cast(self, key):
        """Remove entrada expirada do cache de cast"""
        with self.db_lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM cast_cache WHERE cache_key = ?', (key,))
            conn.commit()
            conn.close()
    
    def cleanup_expired(self):
        """Remove todas as entradas expiradas"""
        current_time = int(time.time())
        
        with self.db_lock:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Limpa cast cache expirado
            cursor.execute('''
                DELETE FROM cast_cache WHERE (? - timestamp) > ttl
            ''', (current_time,))
            
            # Limpa conversões IMDB→TMDB expiradas
            cursor.execute('''
                DELETE FROM imdb_tmdb_map WHERE (? - timestamp) > ?
            ''', (current_time, CACHE_TTL_IMDB_MAP))
            
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
        
        if deleted > 0:
            xbmc.log('[script.embuary.info] Cleaned up %d expired cache entries' % deleted, xbmc.LOGDEBUG)
    
    def shutdown(self):
        """Shutdown gracioso - flush da fila e para worker"""
        xbmc.log('[script.embuary.info] Shutting down cache manager...', xbmc.LOGINFO)
        
        # Para worker
        self.worker_running = False
        
        # Flush final da fila
        self._flush_queue()
        
        xbmc.log('[script.embuary.info] Cache manager shutdown complete', xbmc.LOGINFO)

########################

# Instância global (singleton)
_cache_manager = None

def get_cache_manager():
    """Retorna instância singleton do cache manager"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CastCacheManager()
    return _cache_manager
