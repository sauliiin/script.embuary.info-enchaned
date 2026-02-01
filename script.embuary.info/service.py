#!/usr/bin/python
# -*- coding: utf-8 -*-

import xbmc
import xbmcaddon
import xbmcgui
import json
import time
from threading import Thread, Lock

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')

class CastPreloader(xbmc.Monitor):
    def __init__(self):
        super(CastPreloader, self).__init__()
        self.current_item = None
        self.processing = False
        self.lock = Lock()
        
        # Importa módulos de cache e async loader
        from resources.lib.cache_manager import get_cache_manager
        from resources.lib.async_loader import get_async_loader

        # PERMANENT WARM-UP: Import heavy modules here to keep them in sys.modules
        # This prevents them from being unloaded on skin reload/script completion
        try:
            import sqlite3
            import json
            import datetime
            import time
            from resources.lib.video import TMDBVideos
            from resources.lib.tmdb import tmdb_query
            xbmc.log('[%s] Permanent references pinned for warm-up' % ADDON_ID, xbmc.LOGINFO)
        except Exception:
            pass
        
        self.cache_manager = get_cache_manager()

        self.async_loader = get_async_loader()
        
        xbmc.log('[%s] Cast Preloader Service Started' % ADDON_ID, xbmc.LOGINFO)
        
        xbmc.log('[%s] Cast Preloader Service Started' % ADDON_ID, xbmc.LOGINFO)
        
        # NOTE: Warmup logic is now handled by direct imports above.
        # Explicit RunScript call removed to prevent double-initalization delay.

    def preload_cast(self, tmdb_id, media_type, imdb_id=None):
        """Pré-carrega o cast em background"""
        with self.lock:
            if self.processing:
                return
            self.processing = True

        try:
            from resources.lib.tmdb import tmdb_query, tmdb_find
            
            start_time = time.time()
            
            xbmc.log('[%s] ▶ Starting preload for %s (tmdb_id=%s, imdb_id=%s)' % 
                     (ADDON_ID, media_type, tmdb_id if tmdb_id else 'None', imdb_id if imdb_id else 'None'), 
                     xbmc.LOGINFO)
            
            # Conversão IMDB → TMDB se necessário
            if (not tmdb_id or tmdb_id in ['None', '']) and imdb_id:
                xbmc.log('[%s] → Converting IMDB to TMDB...' % ADDON_ID, xbmc.LOGINFO)
                
                # Verifica cache de conversão primeiro
                cached_tmdb_id, cached_media_type = self.cache_manager.get_tmdb_from_imdb(imdb_id)
                
                if cached_tmdb_id:
                    tmdb_id = cached_tmdb_id
                    if cached_media_type:
                        media_type = cached_media_type
                    xbmc.log('[%s] ✓ IMDB→TMDB cache HIT: %s → %s' % (ADDON_ID, imdb_id, tmdb_id), xbmc.LOGINFO)
                else:
                    # Cache miss - converte via API
                    xbmc.log('[%s] ✗ IMDB→TMDB cache MISS: %s - Calling API...' % (ADDON_ID, imdb_id), xbmc.LOGINFO)
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
                            # Salva conversão no cache
                            self.cache_manager.set_imdb_tmdb_map(imdb_id, tmdb_id, media_type)
                    except Exception as e:
                        xbmc.log('[%s] ✗ IMDB→TMDB conversion error: %s' % (ADDON_ID, str(e)), xbmc.LOGERROR)

            if not tmdb_id or tmdb_id == 'None':
                xbmc.log('[%s] ✗ No valid TMDB ID, aborting preload' % ADDON_ID, xbmc.LOGWARNING)
                return

            # Usa async loader para pré-carregar cast
            cast_data = self.async_loader.get_cast_from_cache_or_load(tmdb_id, media_type, self.cache_manager)

        except Exception as e:
            xbmc.log('[%s] ✗ Preload ERROR: %s' % (ADDON_ID, str(e)), xbmc.LOGERROR)

        finally:
            with self.lock:
                self.processing = False

    def check_focused_item(self):
        """Verifica o item atualmente focado"""
        try:
            # Estratégia 1: Tenta pegar TMDB ID direto (plugins que fornecem)
            tmdb_id = xbmc.getInfoLabel('Window(Home).Property(ds_tmdb_id)')
            
            # Estratégia 2: Pega IMDB ID e tipo
            imdb_id = xbmc.getInfoLabel('Window(Home).Property(ds_imdb_id)')
            dbtype = xbmc.getInfoLabel('Window(Home).Property(ds_info_dbtype)')
            

            
            # Detecta tipo de mídia
            media_type = None
            if dbtype == 'movie':
                media_type = 'movie'
            elif dbtype in ['tvshow', 'season', 'episode']:
                media_type = 'tv'
            
            # Fallback: tenta ContextMenuTargetID (compatibilidade)
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

            # Cria identificador único do item
            item_id = '%s_%s_%s' % (media_type, tmdb_id if tmdb_id else '', imdb_id if imdb_id else '')

            # Se mudou de item, pré-carrega
            if item_id != self.current_item:
                self.current_item = item_id
                
                # Executa em thread separada para não bloquear
                # Busca Cast (existente) E Metadata (solicitado)
                def _background_worker(t_id, m_type, i_id):
                    self.preload_cast(t_id, m_type, i_id)
                    self.fetch_and_set_metadata(t_id, i_id, m_type)

                Thread(target=_background_worker, args=(tmdb_id, media_type, imdb_id)).start()

        except Exception as e:
            xbmc.log('[%s] Check error: %s' % (ADDON_ID, str(e)), xbmc.LOGDEBUG)

    def fetch_and_set_metadata(self, tmdb_id, imdb_id, media_type):
        """Busca metadata (Budget, Revenue, MPAA, Awards) e define via SetProperty (Thread-Safe)"""
        try:
            from resources.lib.tmdb import tmdb_query, tmdb_get_cert, format_currency
            from resources.lib.omdb import omdb_api
            
            # --- TMDB Data (Budget, Revenue, MPAA) ---
            if tmdb_id:
                movie_data = tmdb_query(
                    action='movie',
                    call=str(tmdb_id),
                    params={'append_to_response': 'release_dates'},
                    show_error=False
                )
                        
                if movie_data:
                    budget_val = format_currency(movie_data.get('budget'))
                    revenue_val = format_currency(movie_data.get('revenue'))
                    mpaa_val = tmdb_get_cert(movie_data)
                    
                    if budget_val: 
                        xbmc.executebuiltin('SetProperty(budget,"%s",home)' % budget_val)
                    if revenue_val: 
                        xbmc.executebuiltin('SetProperty(revenue,"%s",home)' % revenue_val)
                    if mpaa_val: 
                        xbmc.executebuiltin('SetProperty(mpaa,"%s",home)' % mpaa_val)
                    
                    # Studios
                    studios = movie_data.get('production_companies', [])
                    if studios:
                        studio_str = ', '.join([s['name'] for s in studios])
                        # Basic escape
                        studio_str = studio_str.replace('"', "'")
                        xbmc.executebuiltin('SetProperty(studio,"%s",home)' % studio_str)

                    # Countries
                    countries = movie_data.get('production_countries', [])
                    if countries:
                        country_str = ', '.join([c['name'] for c in countries])
                        country_str = country_str.replace('"', "'")
                        xbmc.executebuiltin('SetProperty(country,"%s",home)' % country_str)
                
                # Update IMDB ID from TMDB if missing
                if not imdb_id and movie_data:
                    imdb_id = movie_data.get('imdb_id')

            # --- OMDB Data (Awards) ---
            if imdb_id:
                try:
                    omdb_data = omdb_api(imdb_id)
                    if omdb_data and omdb_data.get('awards'):
                        # Escape any special chars if necessary, though basic strings are usually safe
                        awards = omdb_data['awards'].replace('"', "'") # Prevent breaking quotes
                        xbmc.executebuiltin('SetProperty(awards,"%s",home)' % awards)
                except:
                    pass

        except Exception as e:
            xbmc.log('[%s] Metadata Fetch Error: %s' % (ADDON_ID, str(e)), xbmc.LOGWARNING)

    def fetch_and_set_reviews(self, tmdb_id, media_type):
        """Busca reviews do Trakt e define via SetProperty (Thread-Safe)"""
        try:
            from resources.lib.tmdb import tmdb_get_combined_reviews
            
            reviews = tmdb_get_combined_reviews(tmdb_id, media_type=media_type)
            
            if reviews:
                # Cleaning string for SetProperty to avoid breaking the command
                import urllib.parse
                # Quote the reviews content as well
                safe_reviews = reviews.replace('"', "'")
                xbmc.executebuiltin('SetProperty(Trakt.Reviews,"%s",home)' % safe_reviews)
            else:
                 xbmc.executebuiltin('ClearProperty(Trakt.Reviews,home)')

        except Exception as e:
            xbmc.log('[%s] Reviews Fetch Error: %s' % (ADDON_ID, str(e)), xbmc.LOGWARNING)

    def run(self):
        """Loop principal do serviço"""
        check_interval = 0.5  # Verifica a cada 0.5 segundo
        
        last_infoid = None
        last_playerid = None

        while not self.abortRequested():
             if self.waitForAbort(check_interval):
                break
             
             # 1. Logic for DialogVideoInfo (Metadata)
             if xbmc.getCondVisibility('Window.IsActive(movieinformation)'):
                 try:
                     tmdb_id = xbmc.getInfoLabel('ListItem.UniqueID(tmdb)')
                     imdb_id = xbmc.getInfoLabel('ListItem.IMDBNumber')
                     
                     current_infoid = '%s_%s' % (tmdb_id, imdb_id)
                     
                     if current_infoid != last_infoid and (tmdb_id or imdb_id):
                         last_infoid = current_infoid
                         
                         Thread(target=self.fetch_and_set_metadata, args=(tmdb_id, imdb_id, 'movie')).start()
                 except: pass
             else:
                 last_infoid = None

             # 2. Logic for DialogSeekBar/OSD (Metadata for Playing Item)
             if xbmc.getCondVisibility('Player.HasVideo') and (xbmc.getCondVisibility('Window.IsActive(videoosd)') or xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)') or xbmc.getCondVisibility('Window.IsActive(seekbardialog)')):
                 try:
                     p_tmdb = xbmc.getInfoLabel('VideoPlayer.UniqueID(tmdb)')
                     if not p_tmdb:
                         p_tmdb = xbmc.getInfoLabel('VideoPlayer.UniqueID')

                     p_imdb = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
                     
                     # Simple logic to update when player starts
                     current_playerid = '%s' % (p_tmdb)
                     
                     if current_playerid != last_playerid and p_tmdb:
                         last_playerid = current_playerid
                         # Fetch metadata (Budget, Studio, etc) for the PLAYING video
                         Thread(target=self.fetch_and_set_metadata, args=(p_tmdb, p_imdb, 'movie')).start()
                 except: pass
             else:
                 last_playerid = None

            # 3. Widget Preloader Logic (Focus Monitor)
             # User requested instant metadata. This method monitors ds_tmdb_id changes on Home.
             self.check_focused_item()
             
        # Shutdown gracioso
        xbmc.log('[%s] Shutting down service...' % ADDON_ID, xbmc.LOGINFO)
        self.cache_manager.shutdown()
        self.async_loader.shutdown()
        xbmc.log('[%s] Cast Preloader Service Stopped' % ADDON_ID, xbmc.LOGINFO)

if __name__ == '__main__':
    monitor = CastPreloader()
    monitor.run()
