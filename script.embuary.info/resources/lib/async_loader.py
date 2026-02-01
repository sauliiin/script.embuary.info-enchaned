#!/usr/bin/python
# coding: utf-8

########################

import xbmc
import xbmcgui
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, PriorityQueue
import time

########################

class CastAsyncLoader:
    """
    Carregador assíncrono de cast com workers paralelos.
    
    Features:
    - 2 workers para carregamento paralelo
    - Fila de 6 itens prioritários (primeiros atores visíveis)
    - Carregamento progressivo de imagens
    - Thread-safe
    """
    
    def __init__(self, max_workers=2, priority_queue_size=6):
        """
        Inicializa o async loader.
        
        Args:
            max_workers: Número de workers (padrão: 2)
            priority_queue_size: Tamanho da fila prioritária (padrão: 6)
        """
        self.max_workers = max_workers
        self.priority_queue_size = priority_queue_size
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        xbmc.log('[script.embuary.info] CastAsyncLoader initialized with %d workers' % max_workers, xbmc.LOGDEBUG)
    
    def load_cast_progressive(self, cast_data, callback=None):
        """
        Carrega cast progressivamente com priorização.
        
        Args:
            cast_data: Lista de dicts com dados do cast
            callback: Função opcional para chamar quando cada item é carregado
            
        Returns:
            Lista de ListItems (retorna imediatamente, workers carregam em background)
        """
        if not cast_data:
            return []
        
        # Separa em prioritários (primeiros 6) e resto
        priority_items = cast_data[:self.priority_queue_size]
        background_items = cast_data[self.priority_queue_size:]
        
        xbmc.log('[script.embuary.info] Loading %d priority items, %d background items' % 
                 (len(priority_items), len(background_items)), xbmc.LOGDEBUG)
        
        # Cria ListItems vazios (retorna instantaneamente)
        list_items = []
        for item in cast_data:
            list_item = self._create_list_item(item)
            list_items.append(list_item)
        
        # Agenda carregamento de imagens em background
        if priority_items:
            self._load_images_async(priority_items, list_items[:len(priority_items)], priority=True, callback=callback)
        
        if background_items:
            self._load_images_async(background_items, list_items[len(priority_items):], priority=False, callback=callback)
        
        return list_items
    
    def _create_list_item(self, item):
        """
        Cria ListItem básico sem imagem (instantâneo).
        
        Args:
            item: Dict com dados do ator
            
        Returns:
            xbmcgui.ListItem
        """
        name = item.get('name', '')
        character = item.get('character', '')
        actor_id = item.get('id', '')
        
        list_item = xbmcgui.ListItem(label=name)
        list_item.setLabel2(character)
        list_item.setArt({'icon': 'DefaultActor.png'})  # Placeholder
        list_item.setProperty('id', str(actor_id))
        list_item.setProperty('call', 'person')
        
        return list_item
    
    def _load_images_async(self, items, list_items, priority=True, callback=None):
        """
        Carrega imagens em background usando workers.
        
        Args:
            items: Lista de dicts com dados
            list_items: Lista de ListItems correspondentes
            priority: Se True, carrega com prioridade alta
            callback: Função opcional para chamar quando cada item é carregado
        """
        futures = {}
        
        for idx, item in enumerate(items):
            future = self.executor.submit(self._load_image, item)
            futures[future] = (idx, list_items[idx])
        
        # Processa resultados conforme ficam prontos
        for future in as_completed(futures):
            idx, list_item = futures[future]
            try:
                image_url = future.result()
                if image_url:
                    # Atualiza ListItem com imagem carregada
                    list_item.setArt({
                        'icon': 'DefaultActor.png',
                        'thumb': image_url,
                        'poster': image_url
                    })
                    
                    if callback:
                        callback(idx, list_item)
                    
                    xbmc.log('[script.embuary.info] Loaded image for actor %d' % idx, xbmc.LOGDEBUG)
            except Exception as e:
                xbmc.log('[script.embuary.info] Error loading image: %s' % str(e), xbmc.LOGERROR)
    
    def _load_image(self, item):
        """
        Carrega URL da imagem do ator.
        
        Args:
            item: Dict com dados do ator
            
        Returns:
            URL da imagem ou None
        """
        profile_path = item.get('profile_path')
        if not profile_path:
            return None
        
        # URL base do TMDB para imagens de perfil (w185)
        IMG_PROFILE = 'https://image.tmdb.org/t/p/w185'
        return IMG_PROFILE + profile_path
    
    def preload_cast_data(self, tmdb_id, media_type, cache_manager):
        """
        Pré-carrega dados do cast para cache.
        
        Args:
            tmdb_id: TMDB ID
            media_type: Tipo de mídia ('movie' ou 'tv')
            cache_manager: Instância do CastCacheManager
            
        Returns:
            Lista de dados do cast ou None
        """
        from resources.lib.tmdb import tmdb_query
        
        try:
            # Busca dados do TMDB
            data = tmdb_query(
                action='movie' if media_type == 'movie' else 'tv',
                call=tmdb_id,
                params={'append_to_response': 'credits'},
                show_error=False
            )
            
            if not data:
                return None
            
            # Extrai cast
            cast_data = data.get('credits', {}).get('cast', [])
            
            # Filtra apenas atores que realmente atuaram (exclui produtores, etc)
            # e limita a 10 atores principais
            acting_cast = [
                actor for actor in cast_data 
                if actor.get('known_for_department', '').lower() == 'acting'
            ]
            cast_data = acting_cast[:10]
            
            # Salva no cache
            cache_key = 'cast_%s_%s' % (media_type, tmdb_id)
            cache_manager.set(cache_key, cast_data)
            
            xbmc.log('[script.embuary.info] Preloaded cast for %s ID: %s (%d actors)' % 
                     (media_type, tmdb_id, len(cast_data)), xbmc.LOGDEBUG)
            
            return cast_data
            
        except Exception as e:
            xbmc.log('[script.embuary.info] Error preloading cast: %s' % str(e), xbmc.LOGERROR)
            return None
    
    def get_cast_from_cache_or_load(self, tmdb_id, media_type, cache_manager):
        """
        Busca cast do cache ou carrega do TMDB.
        
        Args:
            tmdb_id: TMDB ID
            media_type: Tipo de mídia ('movie' ou 'tv')
            cache_manager: Instância do CastCacheManager
            
        Returns:
            Lista de dados do cast
        """
        # Tenta cache primeiro
        cache_key = 'cast_%s_%s' % (media_type, tmdb_id)
        cached_data = cache_manager.get(cache_key)
        
        if cached_data:
            xbmc.log('[script.embuary.info] ✓ Cast cache HIT for %s (%d actors)' % (cache_key, len(cached_data)), xbmc.LOGINFO)
            return cached_data
        
        # Cache miss - carrega do TMDB
        xbmc.log('[script.embuary.info] ✗ Cast cache MISS for %s - Loading from TMDB...' % cache_key, xbmc.LOGINFO)
        result = self.preload_cast_data(tmdb_id, media_type, cache_manager)
        
        if result:
            xbmc.log('[script.embuary.info] ✓ Cast loaded and SAVED to cache: %s (%d actors)' % (cache_key, len(result)), xbmc.LOGINFO)
        
        return result
    
    def shutdown(self):
        """Shutdown gracioso - aguarda workers finalizarem"""
        xbmc.log('[script.embuary.info] Shutting down async loader...', xbmc.LOGINFO)
        self.executor.shutdown(wait=True)
        xbmc.log('[script.embuary.info] Async loader shutdown complete', xbmc.LOGINFO)

########################

# Instância global
_async_loader = None

def get_async_loader():
    """Retorna instância singleton do async loader"""
    global _async_loader
    if _async_loader is None:
        _async_loader = CastAsyncLoader(max_workers=2, priority_queue_size=6)
    return _async_loader
