#!/usr/bin/python
# -*- coding: utf-8 -*-

import xbmc
import xbmcaddon
import xbmcgui
import time
from datetime import date
from threading import Thread, Lock

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')

# ============================================================
# Caches em MEMÓRIA (acesso instantâneo)
# ============================================================
_cast_bios_cache = {}
_cast_bios_lock = Lock()
_generated_bios_text_cache = {}
_generated_bios_lock = Lock()
_imdb_tmdb_memory_cache = {}
_imdb_tmdb_lock = Lock()
BIOS_CACHE_MAX_AGE = 86400 * 30

class CastPreloader(xbmc.Monitor):
    _cast_cache_memory = {}
    _processing_keys = set()
    _processing_lock = Lock()
    
    INTERVAL_FAST = 0.3
    INTERVAL_NORMAL = 0.5
    INTERVAL_SLOW = 2.0
    INTERVAL_IDLE = 3.0
    
    def __init__(self):
        super(CastPreloader, self).__init__()
        self.current_item = None
        self._last_context = 'unknown'
        self._playing_item_cache = {}
        self._last_bios_update_id = None
        self._bios_updating = False
        self._warmup_complete = False
        
        # Imports LEVES apenas - necessários para cast
        from resources.lib.cache_manager import get_cache_manager
        from resources.lib.async_loader import get_async_loader
        
        self.cache_manager = get_cache_manager()
        self.async_loader = get_async_loader()
        
        xbmc.log('[%s] Cast Preloader Initialized' % ADDON_ID, xbmc.LOGINFO)

    # ============================================================
    # WARM-UP: Service cache + Plugin libraries
    # ============================================================
    def _warmup_cache_on_startup(self):
        try:
            start = time.time()
            
            # 1. Warm-up do cache (dados)
            recent_cast = self.cache_manager.get_recent_items('cast_', limit=1)
            if recent_cast:
                CastPreloader._cast_cache_memory.update(recent_cast)
            
            self._warmup_complete = True
            xbmc.log('[%s] Service Warm-up: %.2fs (cast:%d)' % 
                     (ADDON_ID, time.time() - start, len(recent_cast or {})), xbmc.LOGINFO)
                     
        except Exception as e:
            xbmc.log('[%s] Service Warm-up error: %s' % (ADDON_ID, e), xbmc.LOGWARNING)
            self._warmup_complete = True

    def _warmup_plugin_on_startup(self):
        """Aciona warm-up do plugin para pré-carregar bibliotecas pesadas"""
        try:
            xbmc.log('[%s] Triggering Plugin Warm-up...' % ADDON_ID, xbmc.LOGINFO)
            
            # Aguarda um pouco para não sobrecarregar o startup
            xbmc.sleep(1000)  # 1 segundo
            
            # Chama o plugin em modo warmup (não bloqueia, retorna rápido)
            xbmc.executebuiltin('RunScript(script.embuary.info,mode=warmup)', wait=False)
            
            xbmc.log('[%s] Plugin Warm-up triggered' % ADDON_ID, xbmc.LOGINFO)
        except Exception as e:
            xbmc.log('[%s] Plugin Warm-up trigger failed: %s' % (ADDON_ID, e), xbmc.LOGWARNING)

    # ============================================================
    # CAST - RÁPIDO E SEM BLOQUEIO
    # ============================================================
    def preload_cast(self, tmdb_id, media_type, imdb_id=None):
        try:
            # Resolve TMDB ID se necessário
            if (not tmdb_id or tmdb_id in ['None', '']) and imdb_id:
                tmdb_id, media_type = self._resolve_tmdb_id(imdb_id, media_type)
            
            if not tmdb_id or tmdb_id == 'None':
                return None

            cache_key = 'cast_%s_%s' % (media_type, tmdb_id)
            
            # 1. CACHE HIT - Retorna instantâneo
            if cache_key in CastPreloader._cast_cache_memory:
                return CastPreloader._cast_cache_memory[cache_key]
            
            # 2. Verifica se já está sendo processado
            with self._processing_lock:
                if cache_key in self._processing_keys:
                    return None
                self._processing_keys.add(cache_key)
            
            try:
                # 3. CACHE MISS - Busca
                cast_data = self.async_loader.get_cast_from_cache_or_load(
                    tmdb_id, media_type, self.cache_manager
                )
                
                if cast_data:
                    CastPreloader._cast_cache_memory[cache_key] = cast_data
                    return cast_data
                    
            finally:
                with self._processing_lock:
                    self._processing_keys.discard(cache_key)
                    
        except Exception as e:
            xbmc.log('[%s] Cast error: %s' % (ADDON_ID, e), xbmc.LOGERROR)
        
        return None

    # ============================================================
    # NOVO MÉTODO: Popula Window Properties para XML
    # ============================================================
    def populate_cast_properties(self, tmdb_id, media_type, imdb_id=None, window_id=10000):
        """Popula Window Properties com cast para uso direto no XML"""
        try:
            win = xbmcgui.Window(window_id)

            # Limpa properties antigas
            for i in range(10):
                win.clearProperty('Cast.%d.Name' % i)
                win.clearProperty('Cast.%d.Role' % i)
                win.clearProperty('Cast.%d.Thumb' % i)
                win.clearProperty('Cast.%d.ID' % i)
            win.clearProperty('Cast.Count')

            # Resolve TMDB ID se necessário
            if (not tmdb_id or tmdb_id in ['None', '']) and imdb_id:
                tmdb_id, media_type = self._resolve_tmdb_id(imdb_id, media_type)

            if not tmdb_id or tmdb_id == 'None':
                return

            # Tenta cache primeiro
            cache_key = 'cast_%s_%s' % (media_type, tmdb_id)
            cast_data = CastPreloader._cast_cache_memory.get(cache_key)

            if not cast_data:
                cast_data = self.async_loader.get_cast_from_cache_or_load(
                    tmdb_id, media_type, self.cache_manager
                )
                if cast_data:
                    CastPreloader._cast_cache_memory[cache_key] = cast_data

            # Fallback: busca direto do TMDB
                if not cast_data:
                    # Usa helper atualizado que retorna profile_path
                    cast_data = self._get_movie_cast_from_tmdb(tmdb_id, media_type)

            # Popula properties
            count = 0
            
            if isinstance(cast_data, list):
                for i, actor in enumerate(cast_data[:10]):
                    if isinstance(actor, dict):
                        name = actor.get('name', '')
                        
                        # ★★★ CORREÇÃO: Verifica 'thumb' E 'profile_path' ★★★
                        thumb = actor.get('thumb', '')
                        if not thumb:
                            profile_path = actor.get('profile_path', '')
                            if profile_path:
                                thumb = 'https://image.tmdb.org/t/p/w185%s' % profile_path
                        
                        role = actor.get('role', '') or actor.get('character', '')
                        
                        win.setProperty('Cast.%d.Name' % i, name)
                        win.setProperty('Cast.%d.Role' % i, role)
                        win.setProperty('Cast.%d.Thumb' % i, thumb)
                        win.setProperty('Cast.%d.ID' % i, str(actor.get('id', '')))
                        
                        
                        count += 1

            win.setProperty('Cast.Count', str(count))
            

        except Exception as e:
            xbmc.log('[%s] Error populating cast properties: %s' % (ADDON_ID, e), xbmc.LOGERROR)
            import traceback
            xbmc.log('[%s] Traceback: %s' % (ADDON_ID, traceback.format_exc()), xbmc.LOGERROR)

    def _resolve_tmdb_id(self, imdb_id, media_type):
        # 1. Cache memória
        with _imdb_tmdb_lock:
            if imdb_id in _imdb_tmdb_memory_cache:
                cached = _imdb_tmdb_memory_cache[imdb_id]
                return cached.get('tmdb_id'), cached.get('media_type', media_type)
        
        # 2. Cache disco
        cached_tmdb_id, cached_media_type = self.cache_manager.get_tmdb_from_imdb(imdb_id)
        if cached_tmdb_id:
            with _imdb_tmdb_lock:
                _imdb_tmdb_memory_cache[imdb_id] = {'tmdb_id': cached_tmdb_id, 'media_type': cached_media_type}
            return cached_tmdb_id, cached_media_type or media_type
        
        # 3. API (import tardio)
        try:
            from resources.lib.tmdb import tmdb_query
            find_data = tmdb_query(
                action='find', 
                call=imdb_id, 
                params={'external_source': 'imdb_id'}, 
                show_error=False
            )
            results_key = 'movie_results' if media_type == 'movie' else 'tv_results'
            if find_data and results_key in find_data and find_data[results_key]:
                tmdb_id = find_data[results_key][0]['id']
                self.cache_manager.set_imdb_tmdb_map(imdb_id, tmdb_id, media_type)
                with _imdb_tmdb_lock:
                    _imdb_tmdb_memory_cache[imdb_id] = {'tmdb_id': tmdb_id, 'media_type': media_type}
                return tmdb_id, media_type
        except:
            pass
        
        return None, media_type

    # ============================================================
    # Biografias (imports tardios)
    # ============================================================
    def _calculate_age(self, birthday_str, deathday_str=None):
        if not birthday_str:
            return None
        try:
            import datetime
            birth = datetime.datetime.strptime(birthday_str, "%Y-%m-%d").date()
            end = datetime.datetime.strptime(deathday_str, "%Y-%m-%d").date() if deathday_str else date.today()
            age = end.year - birth.year
            if (end.month, end.day) < (birth.month, birth.day):
                age -= 1
            return age
        except:
            return None

    def _format_date_br(self, date_str):
        if not date_str:
            return None
        try:
            import datetime
            return datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
        except:
            return None

    def _get_person_details_cached(self, person_id):
        cache_key = 'person_bio_%s' % person_id
        
        # Cache memória
        with _cast_bios_lock:
            if cache_key in _cast_bios_cache:
                cached = _cast_bios_cache[cache_key]
                if time.time() - cached['ts'] < BIOS_CACHE_MAX_AGE:
                    return cached['data'], True
        
        # API (import tardio)
        try:
            from resources.lib.tmdb import tmdb_query
            details = None
            
            for attempt in range(3):
                details = tmdb_query(
                    action='person',
                    call=str(person_id),
                    params={'language': 'pt-BR'},
                    show_error=False
                )
                if details:
                    break
                time.sleep(0.5)
            
            if details:
                with _cast_bios_lock:
                    _cast_bios_cache[cache_key] = {'data': details, 'ts': time.time()}
                try:
                    self.cache_manager.set(cache_key, details)
                except:
                    pass
                return details, False
            return None, False
        except:
            return None, False

    def _format_actor_bio(self, actor_name, person_details):
        if not person_details:
            return None
        
        birthday_raw = person_details.get('birthday')
        deathday_raw = person_details.get('deathday')
        place_of_birth_raw = person_details.get('place_of_birth')
        
        age = self._calculate_age(birthday_raw, deathday_raw)
        birthday_formatted = self._format_date_br(birthday_raw)
        deathday_formatted = self._format_date_br(deathday_raw)
        place_of_birth = place_of_birth_raw.strip() if place_of_birth_raw else None
        is_dead = deathday_raw is not None and deathday_raw != ''
             
             
        name_part = "[B]%s[/B]" % actor_name
        
        if is_dead:
            if age is not None and deathday_formatted and birthday_formatted and place_of_birth:
                return "%s (%s – %s), natural de %s, faleceu aos %d anos de idade." % (name_part, birthday_formatted, deathday_formatted, place_of_birth, age)
            elif age is not None and deathday_formatted and birthday_formatted:
                return "%s (%s – %s), faleceu aos %d anos de idade." % (name_part, birthday_formatted, deathday_formatted, age)
            elif age is not None and deathday_formatted:
                return "%s faleceu em %s aos %d anos." % (name_part, deathday_formatted, age)
            elif deathday_formatted:
                return "%s faleceu em %s." % (name_part, deathday_formatted)
            elif age is not None:
                return "%s tinha %d anos quando faleceu." % (name_part, age)
            return None
        else:
            if age is not None and birthday_formatted and place_of_birth:
                return "%s possui %d anos, nasceu em %s, em %s." % (name_part, age, birthday_formatted, place_of_birth)
            elif age is not None and birthday_formatted:
                return "%s possui %d anos, nasceu em %s." % (name_part, age, birthday_formatted)
            elif age is not None:
                return "%s possui %d anos." % (name_part, age)
            elif birthday_formatted and place_of_birth:
                return "%s nasceu em %s em %s." % (name_part, birthday_formatted, place_of_birth)
            elif place_of_birth:
                return "%s nasceu em %s." % (name_part, place_of_birth)
            return None

    def _get_movie_cast_from_tmdb(self, tmdb_id, media_type):
        try:
            from resources.lib.tmdb import tmdb_query
            action = 'tv' if media_type == 'tv' else 'movie'
            details = tmdb_query(
                action=action,
                call=str(tmdb_id),
                params={'append_to_response': 'credits', 'language': 'pt-BR'},
                show_error=False
            )
            
            if not details:
                return []
            
            cast = details.get('credits', {}).get('cast', [])
            return [{'name': a.get('name', ''), 'id': a.get('id'), 'character': a.get('character', ''), 'profile_path': a.get('profile_path', '')} for a in cast[:10]]
        except:
            return []

    def _generate_cast_bios_text(self, tmdb_id, media_type, max_actors=10):
        if not tmdb_id:
            return ""
        
        cache_key = 'bios_text_%s_%s' % (media_type, tmdb_id)
        
        # Cache memória
        with _generated_bios_lock:
            if cache_key in _generated_bios_text_cache:
                cached = _generated_bios_text_cache[cache_key]
                if time.time() - cached['ts'] < BIOS_CACHE_MAX_AGE:
                    return cached['text']
        
        cast = self._get_movie_cast_from_tmdb(tmdb_id, media_type)
        if not cast:
            return ""
        
        bios = []
        for actor in cast[:max_actors]:
            if not actor.get('id'):
                continue
            person_details, _ = self._get_person_details_cached(actor['id'])
            if person_details:
                bio = self._format_actor_bio(actor['name'], person_details)
                if bio:
                    bios.append(bio)
        
        result_text = "[CR][CR]".join(bios)
        
        if result_text:
            with _generated_bios_lock:
                _generated_bios_text_cache[cache_key] = {'text': result_text, 'ts': time.time()}
            try:
                self.cache_manager.set(cache_key, result_text)
            except:
                pass
        
        return result_text

    def _update_cast_bios_property(self, tmdb_id, media_type, window_id=10000):
        if self._bios_updating:
            return
        
        self._bios_updating = True
        
        try:
            win = xbmcgui.Window(window_id)
            
            if not xbmc.Player().isPlayingVideo() and window_id == 10000:
                win.clearProperty('ds_cast_bios')
                return
            
            current_id = '%s_%s' % (media_type, tmdb_id)
            if current_id == self._last_bios_update_id:
                return
            
            self._last_bios_update_id = current_id
            bios_text = self._generate_cast_bios_text(tmdb_id, media_type, max_actors=10)
            
            if bios_text:
                win.setProperty('ds_cast_bios', bios_text)
            else:
                win.clearProperty('ds_cast_bios')
        except:
            pass
        finally:
            self._bios_updating = False

    def _clear_cast_bios_property(self):
        try:
            xbmcgui.Window(10000).clearProperty('ds_cast_bios')
            self._last_bios_update_id = None
        except:
            pass

    # ============================================================
    # Eventos do Kodi
    # ============================================================
    def onNotification(self, sender, method, data):
        try:
            if method == 'Player.OnStop':
                self._clear_cast_bios_property()
            elif method == 'Player.OnPlay':
                self._last_bios_update_id = None
        except:
            pass

    def _get_adaptive_interval(self):
        is_playing = xbmc.getCondVisibility('Player.HasVideo')
        is_fullscreen = xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)')
        is_home = xbmc.getCondVisibility('Window.IsActive(home)')
        is_videoinfo = xbmc.getCondVisibility('Window.IsActive(movieinformation)')
        
        if is_videoinfo:
            return self.INTERVAL_FAST, 'videoinfo'
        elif is_home and not is_playing:
            return self.INTERVAL_FAST, 'home_active'
        elif is_fullscreen:
            return self.INTERVAL_SLOW, 'fullscreen'
        elif is_playing:
            return self.INTERVAL_NORMAL, 'playing'
        else:
            return self.INTERVAL_IDLE, 'idle'

    def check_focused_item(self):
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
                return
            if not media_type:
                return

            item_id = '%s_%s_%s' % (media_type, tmdb_id or '', imdb_id or '')

            if item_id != self.current_item:
                self.current_item = item_id
                
                def _worker(t_id, m_type, i_id):
                    self.preload_cast(t_id, m_type, i_id)
                    self.fetch_and_set_metadata(t_id, i_id, m_type)
                    self.populate_cast_properties(t_id, m_type, i_id)  # ← ADICIONADO

                Thread(target=_worker, args=(tmdb_id, media_type, imdb_id)).start()
        except:
            pass

    def fetch_and_set_metadata(self, tmdb_id, imdb_id, media_type, window_id=10000):
        try:
            meta_cache_key = 'meta_%s_%s' % (media_type, tmdb_id)
            cached_meta = self.cache_manager.get(meta_cache_key)
            
            if cached_meta:
                for key, value in cached_meta.items():
                    if value:
                        xbmc.executebuiltin('SetProperty(%s,"%s",%d)' % (key, value, window_id))
                    else:
                        xbmc.executebuiltin('ClearProperty(%s,%d)' % (key, window_id))
                return

            # Imports tardios - só carrega quando precisa
            from resources.lib.tmdb import tmdb_query, tmdb_get_cert, format_currency
            from resources.lib.omdb import omdb_api
            
            meta_dict = {'budget': '', 'revenue': '', 'mpaa': '', 'studio': '', 'country': '', 'awards': '', 'imdb_combined': ''}
            
            if tmdb_id:
                if media_type == 'tv':
                    tv_data = tmdb_query(
                        action='tv',
                        call=str(tmdb_id),
                        params={'append_to_response': 'content_ratings,external_ids'},
                        show_error=False
                    )
                    
                    # FALLBACK: Se falhar e tiver IMDB, tenta achar o ID correto
                    if not tv_data and imdb_id:
                        new_tmdb_id, _ = self._resolve_tmdb_id(imdb_id, 'tv')
                        if new_tmdb_id and str(new_tmdb_id) != str(tmdb_id):
                            tv_data = tmdb_query(
                                action='tv',
                                call=str(new_tmdb_id),
                                params={'append_to_response': 'content_ratings,external_ids'},
                                show_error=False
                            )

                    if tv_data:
                        meta_dict['mpaa'] = tmdb_get_cert(tv_data) or ''
                        networks = tv_data.get('networks', [])
                        if networks:
                            meta_dict['studio'] = ', '.join([n['name'] for n in networks]).replace('"', "'")
                        countries = tv_data.get('origin_country', [])
                        if countries:
                            meta_dict['country'] = ', '.join(countries)
                        if not imdb_id:
                            imdb_id = tv_data.get('external_ids', {}).get('imdb_id')
                else:
                    movie_data = tmdb_query(
                        action='movie',
                        call=str(tmdb_id),
                        params={'append_to_response': 'release_dates'},
                        show_error=False
                    )

                    # FALLBACK: Se falhar e tiver IMDB, tenta achar o ID correto
                    if not movie_data and imdb_id:
                        new_tmdb_id, _ = self._resolve_tmdb_id(imdb_id, 'movie')
                        if new_tmdb_id and str(new_tmdb_id) != str(tmdb_id):
                            movie_data = tmdb_query(
                                action='movie',
                                call=str(new_tmdb_id),
                                params={'append_to_response': 'release_dates'},
                                show_error=False
                            )

                    if movie_data:
                        meta_dict['budget'] = format_currency(movie_data.get('budget')) or ''
                        meta_dict['revenue'] = format_currency(movie_data.get('revenue')) or ''
                        meta_dict['mpaa'] = tmdb_get_cert(movie_data) or ''
                        studios = movie_data.get('production_companies', [])
                        if studios:
                            meta_dict['studio'] = ', '.join([s['name'] for s in studios]).replace('"', "'")
                        countries = movie_data.get('production_countries', [])
                        if countries:
                            meta_dict['country'] = ', '.join([c['name'] for c in countries]).replace('"', "'")
                            # 
                        else:
                            # 
                            pass

                        if not imdb_id:
                            imdb_id = movie_data.get('imdb_id')

            if imdb_id:
                try:
                    omdb_data = omdb_api(imdb_id)
                    if omdb_data:
                        if omdb_data.get('awards'):
                            meta_dict['awards'] = omdb_data['awards'].replace('"', "'")
                        
                        # Extrai Rating e Votes
                        rating = omdb_data.get('imdbRating', 'N/A')
                        votes = omdb_data.get('imdbVotes', '0').replace(',', '').replace('.', '')
                        
                        if rating and rating != 'N/A':
                             try:
                                 votes_int = int(votes)
                                 votes_formatted = "{:,}".format(votes_int).replace(",", ".")
                             except:
                                 votes_formatted = votes
                                 
                             meta_dict['imdb_combined'] = '%s (%s votos)' % (rating, votes_formatted)
                except:
                    pass
            
            self.cache_manager.set(meta_cache_key, meta_dict)
            
            for key, value in meta_dict.items():
                if value:
                    xbmc.executebuiltin('SetProperty(%s,"%s",%d)' % (key, value, window_id))
                else:
                    xbmc.executebuiltin('ClearProperty(%s,%d)' % (key, window_id))
        except:
            pass

    def run(self):
        last_infoid = None
        last_preloaded_playing = None

        # WARM-UP completo: Service + Plugin
        Thread(target=self._warmup_cache_on_startup, daemon=True).start()
        Thread(target=self._warmup_plugin_on_startup, daemon=True).start()
        
        xbmc.log('[%s] Service started' % ADDON_ID, xbmc.LOGINFO)

        while not self.abortRequested():
            interval, _ = self._get_adaptive_interval()
            
            if self.waitForAbort(interval):
                break
             
            is_playing = xbmc.getCondVisibility('Player.HasVideo')
            
            # Playing item
            if is_playing:
                try:
                    p_tmdb = xbmc.getInfoLabel('VideoPlayer.UniqueID(tmdb)') or xbmc.getInfoLabel('VideoPlayer.UniqueID')
                    p_imdb = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
                    p_media_type = 'tv' if xbmc.getCondVisibility('VideoPlayer.Content(episodes)') else 'movie'
                    
                    if p_tmdb or p_imdb:
                        self._playing_item_cache = {'tmdb_id': p_tmdb, 'imdb_id': p_imdb, 'media_type': p_media_type}
                    
                    current_playing_id = '%s_%s_%s' % (p_media_type, p_tmdb or '', p_imdb or '')
                    
                    if current_playing_id != last_preloaded_playing and (p_tmdb or p_imdb):
                        # 
                        last_preloaded_playing = current_playing_id
                        
                        # OTIMIZAÇÃO: Se for o mesmo item focado antes, reutiliza cache INSTANTANEAMENTE
                        if self.current_item == current_playing_id:
                             # 
                             self.preload_cast(p_tmdb, p_media_type, p_imdb)
                             self.fetch_and_set_metadata(p_tmdb, p_imdb, p_media_type, window_id=12005)
                             self.populate_cast_properties(p_tmdb, p_media_type, p_imdb, window_id=12005)
                             self._update_cast_bios_property(p_tmdb, p_media_type, window_id=12005)
                        else:
                            def _play_worker(t, i, m):
                                self.preload_cast(t, m, i)
                                self.fetch_and_set_metadata(t, i, m, window_id=12005)
                                self.populate_cast_properties(t, m, i, window_id=12005)
                                self._update_cast_bios_property(t, m, window_id=12005)
                            
                            Thread(target=_play_worker, args=(p_tmdb, p_imdb, p_media_type)).start()
                except:
                    pass
             
            # DialogVideoInfo
            if xbmc.getCondVisibility('Window.IsActive(movieinformation)'):
                try:
                    tmdb_id = xbmc.getInfoLabel('ListItem.UniqueID(tmdb)')
                    imdb_id = xbmc.getInfoLabel('ListItem.IMDBNumber')
                    dbtype = xbmc.getInfoLabel('ListItem.DBType')
                    info_media_type = 'tv' if dbtype in ['tvshow', 'season', 'episode'] else 'movie'
                    
                    current_infoid = '%s_%s_%s' % (info_media_type, tmdb_id, imdb_id)
                    
                    if current_infoid != last_infoid and (tmdb_id or imdb_id):
                        last_infoid = current_infoid
                        
                        def _info_worker(t, i, m):
                            self.preload_cast(t, m, i)
                            self.fetch_and_set_metadata(t, i, m)
                            self.populate_cast_properties(t, m, i)  # ← ADICIONADO
                        
                        Thread(target=_info_worker, args=(tmdb_id, imdb_id, info_media_type)).start()
                except: 
                    pass
            else:
                last_infoid = None

            # OSD Fallback
            if is_playing and (xbmc.getCondVisibility('Window.IsActive(videoosd)') or 
                               xbmc.getCondVisibility('Player.ShowInfo') or
                               xbmc.getCondVisibility('Window.IsActive(fullscreeninfo)')):
                try:
                    p_tmdb = xbmc.getInfoLabel('VideoPlayer.UniqueID(tmdb)') or xbmc.getInfoLabel('VideoPlayer.UniqueID')
                    p_imdb = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
                    p_media_type = 'tv' if xbmc.getCondVisibility('VideoPlayer.Content(episodes)') else 'movie'
                    
                    win = xbmcgui.Window(10000)
                    
                    # Fallback Bios
                    if not win.getProperty('ds_cast_bios') and p_tmdb:
                        Thread(target=self._update_cast_bios_property, args=(p_tmdb, p_media_type, 12005)).start()
                        
                    # Fallback Metadata (incluindo Country)
                    if not win.getProperty('country') and p_tmdb:
                         # 
                         Thread(target=self.fetch_and_set_metadata, args=(p_tmdb, p_imdb, p_media_type, 12005)).start()

                except: 
                    pass

            self.check_focused_item()
        
        # Shutdown
        self._clear_cast_bios_property()
        self.cache_manager.shutdown()
        self.async_loader.shutdown()
        xbmc.log('[%s] Service Stopped' % ADDON_ID, xbmc.LOGINFO)

if __name__ == '__main__':
    monitor = CastPreloader()
    monitor.run()