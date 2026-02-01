#!/usr/bin/python
# -*- coding: utf-8 -*-

import xbmc
import xbmcaddon
import xbmcgui
import json
import time
import sqlite3
import datetime
from threading import Thread, Lock

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')

class CastPreloader(xbmc.Monitor):
    # ============================================================
    # Referências permanentes em nível de classe
    # ============================================================
    _pinned_modules = {}
    _cast_cache_memory = {}
    
    # ============================================================
    # Configurações de frequência adaptativa
    # ============================================================
    INTERVAL_FAST = 0.3
    INTERVAL_NORMAL = 0.5
    INTERVAL_SLOW = 2.0
    INTERVAL_IDLE = 3.0
    
    def __init__(self):
        super(CastPreloader, self).__init__()
        self.current_item = None
        self.processing = False
        self.lock = Lock()
        
        self._info_history = {}
        self._player_preloaded = set()
        
        self._current_interval = self.INTERVAL_NORMAL
        self._last_activity_time = time.time()
        self._last_context = 'unknown'
        
        # Cache do item em reprodução para transição instantânea
        self._playing_item_cache = {}
        self._force_fast_interval = False
        self._fast_interval_until = 0
        
        from resources.lib.cache_manager import get_cache_manager
        from resources.lib.async_loader import get_async_loader

        try:
            from resources.lib.video import TMDBVideos
            from resources.lib.tmdb import tmdb_query
            
            CastPreloader._pinned_modules = {
                'sqlite3': sqlite3,
                'json': json,
                'datetime': datetime,
                'time': time,
                'TMDBVideos': TMDBVideos,
                'tmdb_query': tmdb_query,
            }
            
            xbmc.log('[%s] ✓ Permanent references pinned (%d modules)' % 
                     (ADDON_ID, len(CastPreloader._pinned_modules)), xbmc.LOGINFO)
        except Exception as e:
            xbmc.log('[%s] ✗ Warm-up error: %s' % (ADDON_ID, str(e)), xbmc.LOGWARNING)
        
        self.cache_manager = get_cache_manager()
        self.async_loader = get_async_loader()
        
        CastPreloader._pinned_modules['cache_manager'] = self.cache_manager
        CastPreloader._pinned_modules['async_loader'] = self.async_loader
        
        xbmc.log('[%s] ✓ Cast Preloader Service Started (Adaptive + Instant Transition)' % ADDON_ID, xbmc.LOGINFO)

    # ============================================================
    # Detecta eventos do Kodi instantaneamente
    # ============================================================
    def onNotification(self, sender, method, data):
        """
        Callback chamado INSTANTANEAMENTE quando eventos ocorrem no Kodi.
        Isso elimina o delay de até 2s do polling.
        """
        try:
            if method in ['Player.OnStop', 'Player.OnPause', 'Player.OnAVChange']:
                xbmc.log('[%s] ⚡ Instant event: %s' % (ADDON_ID, method), xbmc.LOGINFO)
                self._trigger_instant_preload()
            
            elif method == 'GUI.OnScreensaverDeactivated':
                self._trigger_instant_preload()
                
        except Exception as e:
            xbmc.log('[%s] onNotification error: %s' % (ADDON_ID, str(e)), xbmc.LOGDEBUG)
    
    def _trigger_instant_preload(self):
        """
        Dispara preload instantâneo e força intervalo rápido por 3 segundos.
        """
        self._force_fast_interval = True
        self._fast_interval_until = time.time() + 3.0
        
        if self._playing_item_cache:
            xbmc.log('[%s] ⚡ Instant preload triggered for: %s' % 
                     (ADDON_ID, self._playing_item_cache), xbmc.LOGINFO)
            
            Thread(target=self.preload_cast, args=(
                self._playing_item_cache.get('tmdb_id'),
                self._playing_item_cache.get('media_type', 'movie'),
                self._playing_item_cache.get('imdb_id'),
                True
            )).start()

    def _get_adaptive_interval(self):
        """
        Retorna o intervalo baseado no contexto atual.
        """
        if self._force_fast_interval:
            if time.time() < self._fast_interval_until:
                return self.INTERVAL_FAST, 'forced_fast'
            else:
                self._force_fast_interval = False
        
        is_playing = xbmc.getCondVisibility('Player.HasVideo')
        is_fullscreen = xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)')
        is_home = xbmc.getCondVisibility('Window.IsActive(home)')
        is_videoinfo = xbmc.getCondVisibility('Window.IsActive(movieinformation)')
        
        current_context = 'unknown'
        
        if is_videoinfo:
            current_context = 'videoinfo'
            interval = self.INTERVAL_FAST
            
        elif is_home and not is_playing:
            current_context = 'home_active'
            interval = self.INTERVAL_FAST
            
        elif is_home and is_playing:
            current_context = 'home_background'
            interval = self.INTERVAL_NORMAL
            
        elif is_fullscreen:
            current_context = 'fullscreen'
            interval = self.INTERVAL_SLOW
            
        elif is_playing:
            current_context = 'playing_osd'
            interval = self.INTERVAL_NORMAL
            
        else:
            current_context = 'idle'
            interval = self.INTERVAL_IDLE
        
        if current_context != self._last_context:
            xbmc.log('[%s] 🔄 Context: %s → %s (interval: %.1fs)' % 
                     (ADDON_ID, self._last_context, current_context, interval), xbmc.LOGINFO)
            
            if self._last_context == 'fullscreen' and current_context != 'fullscreen':
                self._trigger_instant_preload()
            
            self._last_context = current_context
        
        return interval, current_context

    def preload_cast(self, tmdb_id, media_type, imdb_id=None, priority=False):
        """Pré-carrega o cast em background"""
        
        if not priority:
            with self.lock:
                if self.processing:
                    return
                self.processing = True
        
        try:
            from resources.lib.tmdb import tmdb_query, tmdb_find
            
            start_time = time.time()
            
            if (not tmdb_id or tmdb_id in ['None', '']) and imdb_id:
                cached_tmdb_id, cached_media_type = self.cache_manager.get_tmdb_from_imdb(imdb_id)
                
                if cached_tmdb_id:
                    tmdb_id = cached_tmdb_id
                    if cached_media_type:
                        media_type = cached_media_type
                else:
                    try:
                        find_data = tmdb_query(
                            action='find', 
                            call=imdb_id, 
                            params={'external_source': 'imdb_id'}, 
                            show_error=False
                        )
                        results_key = 'movie_results' if media_type == 'movie' else 'tv_results'
                        if find_data and results_key in find_data and len(find_data[results_key]) > 0:
                            tmdb_id = find_data[results_key][0]['id']
                            self.cache_manager.set_imdb_tmdb_map(imdb_id, tmdb_id, media_type)
                    except Exception as e:
                        xbmc.log('[%s] ✗ IMDB→TMDB error: %s' % (ADDON_ID, str(e)), xbmc.LOGERROR)

            if not tmdb_id or tmdb_id == 'None':
                return

            cache_key = 'cast_%s_%s' % (media_type, tmdb_id)
            
            if cache_key in CastPreloader._cast_cache_memory:
                return CastPreloader._cast_cache_memory[cache_key]

            cast_data = self.async_loader.get_cast_from_cache_or_load(tmdb_id, media_type, self.cache_manager)
            
            if cast_data:
                CastPreloader._cast_cache_memory[cache_key] = cast_data
                xbmc.log('[%s] ✓ Cached: %s (%.2fs)' % 
                         (ADDON_ID, cache_key, time.time() - start_time), xbmc.LOGINFO)

        except Exception as e:
            xbmc.log('[%s] ✗ Preload ERROR: %s' % (ADDON_ID, str(e)), xbmc.LOGERROR)

        finally:
            if not priority:
                with self.lock:
                    self.processing = False

    def check_focused_item(self):
        """Verifica o item atualmente focado"""
        try:
            tmdb_id = xbmc.getInfoLabel('Window(Home).Property(ds_tmdb_id)')
            imdb_id = xbmc.getInfoLabel('Window(Home).Property(ds_imdb_id)')
            dbtype = xbmc.getInfoLabel('Window(Home).Property(ds_info_dbtype)')
            
            media_type = None
            if dbtype == 'movie':
                media_type = 'movie'
            elif dbtype in ['tvshow', 'season', 'episode']:
                media_type = 'tv'
            
            if not tmdb_id and not imdb_id:
                imdb_id = xbmc.getInfoLabel('Window(Home).Property(ContextMenuTargetID)')
                dbtype = xbmc.getInfoLabel('Window(Home).Property(ContextMenuTargetDBType)')
                
                if dbtype == 'movie':
                    media_type = 'movie'
                elif dbtype in ['tvshow', 'season', 'episode']:
                    media_type = 'tv'
            
            if not tmdb_id and not imdb_id:
                return
            
            if not media_type:
                return

            item_id = '%s_%s_%s' % (media_type, tmdb_id if tmdb_id else '', imdb_id if imdb_id else '')

            if item_id != self.current_item:
                self.current_item = item_id
                self._last_activity_time = time.time()
                
                def _background_worker(t_id, m_type, i_id):
                    self.preload_cast(t_id, m_type, i_id)
                    self.fetch_and_set_metadata(t_id, i_id, m_type)

                Thread(target=_background_worker, args=(tmdb_id, media_type, imdb_id)).start()

        except Exception as e:
            xbmc.log('[%s] Check error: %s' % (ADDON_ID, str(e)), xbmc.LOGDEBUG)

    def fetch_and_set_metadata(self, tmdb_id, imdb_id, media_type):
        """Busca metadata e define via SetProperty - DIFERENCIA FILME DE SÉRIE"""
        try:
            # 1. Verifica Cache Primeiro (Meta Cache)
            meta_cache_key = 'meta_%s_%s' % (media_type, tmdb_id)
            cached_meta = self.cache_manager.get(meta_cache_key)
            
            if cached_meta:
                xbmc.log('[%s] ✓ Metadata cache HIT: %s' % (ADDON_ID, meta_cache_key), xbmc.LOGDEBUG)
                for key, value in cached_meta.items():
                    if value:
                        xbmc.executebuiltin('SetProperty(%s,"%s",home)' % (key, value))
                    else:
                        xbmc.executebuiltin('ClearProperty(%s,home)' % key)
                return

            # 2. Cache MISS - Busca da API
            xbmc.log('[%s] ✗ Metadata cache MISS: %s - Fetching...' % (ADDON_ID, meta_cache_key), xbmc.LOGDEBUG)
            
            from resources.lib.tmdb import tmdb_query, tmdb_get_cert, format_currency
            from resources.lib.omdb import omdb_api
            
            meta_dict = {
                'budget': '',
                'revenue': '',
                'mpaa': '',
                'studio': '',
                'country': '',
                'awards': ''
            }
            
            if tmdb_id:
                # ============================================================
                # SÉRIE: Usa endpoint 'tv' e content_ratings
                # ============================================================
                if media_type == 'tv':
                    tv_data = tmdb_query(
                        action='tv',
                        call=str(tmdb_id),
                        params={'append_to_response': 'content_ratings,external_ids'},
                        show_error=False
                    )
                    
                    if tv_data:
                        # Séries NÃO têm budget/revenue
                        meta_dict['budget'] = ''
                        meta_dict['revenue'] = ''
                        
                        # MPAA para séries usa content_ratings
                        meta_dict['mpaa'] = tmdb_get_cert(tv_data) or ''
                        
                        # Séries usam 'networks' como studio principal
                        networks = tv_data.get('networks', [])
                        if networks:
                            network_str = ', '.join([n['name'] for n in networks])
                            meta_dict['studio'] = network_str.replace('"', "'")
                        else:
                            studios = tv_data.get('production_companies', [])
                            if studios:
                                studio_str = ', '.join([s['name'] for s in studios])
                                meta_dict['studio'] = studio_str.replace('"', "'")
                        
                        # Countries (origin_country para séries)
                        countries = tv_data.get('origin_country', [])
                        if countries:
                            meta_dict['country'] = ', '.join(countries)
                        else:
                            prod_countries = tv_data.get('production_countries', [])
                            if prod_countries:
                                country_str = ', '.join([c['name'] for c in prod_countries])
                                meta_dict['country'] = country_str.replace('"', "'")
                        
                        # Atualiza IMDB ID se não tiver
                        if not imdb_id:
                            imdb_id = tv_data.get('external_ids', {}).get('imdb_id')
                
                # ============================================================
                # FILME: Usa endpoint 'movie' e release_dates
                # ============================================================
                else:
                    movie_data = tmdb_query(
                        action='movie',
                        call=str(tmdb_id),
                        params={'append_to_response': 'release_dates'},
                        show_error=False
                    )
                            
                    if movie_data:
                        budget_val = format_currency(movie_data.get('budget'))
                        revenue_val = format_currency(movie_data.get('revenue'))
                        
                        meta_dict['budget'] = budget_val if budget_val else ''
                        meta_dict['revenue'] = revenue_val if revenue_val else ''
                        meta_dict['mpaa'] = tmdb_get_cert(movie_data) or ''
                        
                        # Studios (production_companies para filmes)
                        studios = movie_data.get('production_companies', [])
                        if studios:
                            studio_str = ', '.join([s['name'] for s in studios])
                            meta_dict['studio'] = studio_str.replace('"', "'")

                        # Countries
                        countries = movie_data.get('production_countries', [])
                        if countries:
                            country_str = ', '.join([c['name'] for c in countries])
                            meta_dict['country'] = country_str.replace('"', "'")
                        
                        # Atualiza IMDB ID se não tiver
                        if not imdb_id:
                            imdb_id = movie_data.get('imdb_id')

            # ============================================================
            # AWARDS: Funciona igual para filme e série (usa IMDB ID)
            # ============================================================
            if imdb_id:
                try:
                    omdb_data = omdb_api(imdb_id)
                    if omdb_data and omdb_data.get('awards'):
                        meta_dict['awards'] = omdb_data['awards'].replace('"', "'")
                except:
                    pass
            
            # 3. Salva no Cache
            self.cache_manager.set(meta_cache_key, meta_dict)
            xbmc.log('[%s] 💾 Metadata cached: %s' % (ADDON_ID, meta_cache_key), xbmc.LOGINFO)
            
            # 4. Aplica Propriedades
            for key, value in meta_dict.items():
                if value:
                    xbmc.executebuiltin('SetProperty(%s,"%s",home)' % (key, value))
                else:
                    xbmc.executebuiltin('ClearProperty(%s,home)' % key)

        except Exception as e:
            xbmc.log('[%s] Metadata Fetch Error: %s' % (ADDON_ID, str(e)), xbmc.LOGWARNING)

    def run(self):
        """Loop principal do serviço"""
        
        last_infoid = None
        last_playerid = None
        last_preloaded_playing = None

        xbmc.log('[%s] 🚀 Adaptive loop started (with instant transitions)' % ADDON_ID, xbmc.LOGINFO)

        while not self.abortRequested():
            interval, context = self._get_adaptive_interval()
            
            if self.waitForAbort(interval):
                break
             
            is_playing = xbmc.getCondVisibility('Player.HasVideo')
            
            # Captura info do item em reprodução (para transição instantânea)
            if is_playing:
                try:
                    p_tmdb = xbmc.getInfoLabel('VideoPlayer.UniqueID(tmdb)')
                    if not p_tmdb:
                        p_tmdb = xbmc.getInfoLabel('VideoPlayer.UniqueID')
                    p_imdb = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
                    
                    p_media_type = 'movie'
                    if xbmc.getCondVisibility('VideoPlayer.Content(episodes)'):
                        p_media_type = 'tv'
                    
                    # SEMPRE atualiza o cache do item em reprodução
                    if p_tmdb or p_imdb:
                        self._playing_item_cache = {
                            'tmdb_id': p_tmdb,
                            'imdb_id': p_imdb,
                            'media_type': p_media_type
                        }
                    
                    current_playing_id = '%s_%s_%s' % (p_media_type, p_tmdb or '', p_imdb or '')
                    
                    if current_playing_id != last_preloaded_playing and (p_tmdb or p_imdb):
                        last_preloaded_playing = current_playing_id
                        
                        xbmc.log('[%s] 🎬 Preloading playing item: %s' % 
                                 (ADDON_ID, current_playing_id), xbmc.LOGINFO)
                        
                        Thread(target=self.preload_cast, args=(p_tmdb, p_media_type, p_imdb)).start()
                except:
                    pass
             
            # DialogVideoInfo
            if xbmc.getCondVisibility('Window.IsActive(movieinformation)'):
                try:
                    tmdb_id = xbmc.getInfoLabel('ListItem.UniqueID(tmdb)')
                    imdb_id = xbmc.getInfoLabel('ListItem.IMDBNumber')
                    dbtype = xbmc.getInfoLabel('ListItem.DBType')
                    
                    # Detecta tipo de mídia
                    if dbtype in ['movie']:
                        info_media_type = 'movie'
                    elif dbtype in ['tvshow', 'season', 'episode']:
                        info_media_type = 'tv'
                    else:
                        # Fallback: tenta detectar pela janela
                        info_media_type = 'movie'
                    
                    current_infoid = '%s_%s_%s' % (info_media_type, tmdb_id, imdb_id)
                    
                    if current_infoid != last_infoid and (tmdb_id or imdb_id):
                        last_infoid = current_infoid
                        
                        def _info_worker(t_id, i_id, m_type):
                            self.preload_cast(t_id, m_type, i_id)
                            self.fetch_and_set_metadata(t_id, i_id, m_type)
                        
                        Thread(target=_info_worker, args=(tmdb_id, imdb_id, info_media_type)).start()
                except: pass

            # OSD/SeekBar
            if is_playing and (xbmc.getCondVisibility('Window.IsActive(videoosd)') or xbmc.getCondVisibility('Window.IsActive(seekbardialog)')):
                try:
                    p_tmdb = xbmc.getInfoLabel('VideoPlayer.UniqueID(tmdb)')
                    if not p_tmdb:
                        p_tmdb = xbmc.getInfoLabel('VideoPlayer.UniqueID')

                    p_imdb = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
                    
                    p_media_type = 'movie'
                    if xbmc.getCondVisibility('VideoPlayer.Content(episodes)'):
                        p_media_type = 'tv'
                    
                    current_playerid = '%s_%s' % (p_media_type, p_tmdb)
                    
                    if current_playerid != last_playerid and p_tmdb:
                        last_playerid = current_playerid
                        Thread(target=self.fetch_and_set_metadata, args=(p_tmdb, p_imdb, p_media_type)).start()
                except: pass

            self.check_focused_item()
              
        xbmc.log('[%s] Shutting down service...' % ADDON_ID, xbmc.LOGINFO)
        self.cache_manager.shutdown()
        self.async_loader.shutdown()
        xbmc.log('[%s] Cast Preloader Service Stopped' % ADDON_ID, xbmc.LOGINFO)

if __name__ == '__main__':
    monitor = CastPreloader()
    monitor.run()