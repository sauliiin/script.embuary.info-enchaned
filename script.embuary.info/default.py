#!/usr/bin/python
# coding=utf-8
import sys
import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin
import urllib.parse

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')

# Flag global para controlar warm-up (persiste enquanto o Kodi estiver rodando)
_WARMUP_DONE = False

def perform_warmup():
    global _WARMUP_DONE

    # Evita refazer warm-up repetidamente no mesmo processo
    if _WARMUP_DONE:
        return

    xbmc.log(f"[{ADDON_ID}] Process Warm-up started", xbmc.LOGINFO)
    try:
        import sqlite3
        import json
        import datetime
        import time
        from resources.lib.video import TMDBVideos
        from resources.lib.tmdb import tmdb_query
        from resources.lib.cache_manager import get_cache_manager

        # Inicializa cache manager para garantir conexão DB
        get_cache_manager()

        xbmc.log(f"[{ADDON_ID}] Process Warm-up finished", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"[{ADDON_ID}] Process Warm-up failed: {str(e)}", xbmc.LOGWARNING)
    finally:
        _WARMUP_DONE = True


def run_as_plugin(handle, params_str):
    try:
        # Limpa e parseia parametros
        params_str = params_str.lstrip('?')
        if not params_str:
            xbmcplugin.endOfDirectory(handle)
            return

        params = dict(urllib.parse.parse_qsl(params_str))
        mode = params.get('mode')

        if mode == 'warmup':
            perform_warmup()
            xbmcplugin.endOfDirectory(handle)
            return

        if mode == 'cast':
            # WARM-UP AUTOMÁTICO: Garante que libs estejam carregadas
            perform_warmup()

            import time
            plugin_start = time.time()

            # Plugin needs to end directory anyway to not hang
            from resources.lib.video import TMDBVideos
            from resources.lib.tmdb import tmdb_query, write_cache

            tmdb_id = params.get('tmdb_id')
            imdb_id = params.get('imdb_id')
            media_type = params.get('type', 'movie')  # movie ou tv

            # 1. Conversão IMDB -> TMDB com cache
            if (not tmdb_id or tmdb_id in ['None', '']) and imdb_id:
                from resources.lib.cache_manager import get_cache_manager
                cache_mgr = get_cache_manager()

                # Tenta cache primeiro
                cached_tmdb_id, cached_media_type = cache_mgr.get_tmdb_from_imdb(imdb_id)
                if cached_tmdb_id:
                    tmdb_id = cached_tmdb_id
                    if cached_media_type:
                        media_type = cached_media_type
                else:
                    # Cache miss - converte via API
                    try:
                        find_data = tmdb_query(action='find', call=imdb_id, 
                                           params={'external_source': 'imdb_id'}, 
                                           show_error=False)
                        results_key = 'movie_results' if media_type == 'movie' else 'tv_results'
                        if find_data and results_key in find_data and len(find_data[results_key]) > 0:
                            tmdb_id = find_data[results_key][0]['id']
                            # Salva no cache
                            cache_mgr.set_imdb_tmdb_map(imdb_id, tmdb_id, media_type)
                    except:
                        pass

            # Validação Final de ID
            if not tmdb_id or tmdb_id == 'None':
                xbmcplugin.endOfDirectory(handle)
                return

            call_params = {
                'call': 'movie' if media_type == 'movie' else 'tv',
                'tmdb_id': tmdb_id,
                'mode': 'cast',
                'local_movies': [],
                'local_shows': []
            }

            try:
                fetcher = TMDBVideos(call_params)
                cast_list = fetcher.get_cast()
            except:
                cast_list = []

            # 3. Cria itens para o Kodi
            for actor in cast_list:
                name = actor.getLabel()
                role = actor.getLabel2()

                # Correção de imagem: Prioriza Thumb -> Poster -> Fallback
                real_image = actor.getArt('thumb')
                if not real_image:
                    real_image = actor.getArt('poster')
                if not real_image:
                    real_image = 'DefaultActorSolid.png'

                li = xbmcgui.ListItem(label=name)
                li.setLabel2(role)
                li.setArt({'icon': real_image, 'thumb': real_image, 'poster': real_image})
                li.setInfo('video', {'title': name, 'plot': role})

                # Ação de clique
                query_name = urllib.parse.quote(name)
                url_action = f"plugin://script.embuary.info/?call=person&query='{query_name}'"
                xbmcplugin.addDirectoryItem(handle=handle, url=url_action, listitem=li, isFolder=False)

            plugin_elapsed = time.time() - plugin_start
            xbmc.log(f"[{ADDON_ID}] Plugin CAST completed in {plugin_elapsed:.3f}s ({len(cast_list)} actors)", xbmc.LOGINFO)

            xbmcplugin.endOfDirectory(handle)
            return

    except Exception:
        # Garante que o loading pare mesmo em erro fatal
        try:
            xbmcplugin.endOfDirectory(handle)
        except:
            pass


class Main:
    def __init__(self):
        self.call = False
        self.params = {}
        self._parse_argv()

        # WARM-UP AUTOMÁTICO: Para modo script também
        if self.params.get('mode') == 'warmup':
            perform_warmup()
            return

        if self.params.get('mode') == 'reset_scroll':
            # OTIMIZAÇÃO: Verifica warm-up ANTES de criar Dialog
            # STRATEGY: Wait for window animation -> Set Property to create control -> Set Focus
            try:
                xbmc.sleep(300)  # Wait for fade in
                xbmc.executebuiltin("SetProperty(ActorList.State,ready)")  # Force Create
                xbmc.sleep(100)  # Wait for render
                xbmc.executebuiltin("Control.SetFocus(50,0)")
                xbmc.executebuiltin("Control.SetFocus(138)")
            except:
                pass
            return

        # Para outros modos script, faz warm-up também
        perform_warmup()

        # Dialog só criado se entrarmos no modo Script real
        self.dialog = xbmcgui.Dialog()

        if self.call == 'textviewer':
            from resources.lib.helper import textviewer
            textviewer(self.params)
        else:
            self.run()

    def run(self):
        from resources.lib.main import TheMovieDB

        if self.call:
            TheMovieDB(self.call, self.params)
        else:
            # Usa self.dialog em vez do DIALOG global
            call = self.dialog.select(ADDON.getLocalizedString(32005), 
                                     [ADDON.getLocalizedString(32004),
                                      xbmc.getLocalizedString(20338),
                                      xbmc.getLocalizedString(20364)])

            if call == 0:
                call = 'person'
            elif call == 1:
                call = 'movie'
            elif call == 2:
                call = 'tv'
            else:
                return

            query = self.dialog.input(xbmc.getLocalizedString(19133), type=xbmcgui.INPUT_ALPHANUM)
            TheMovieDB(call, {'query': query})

    def _parse_argv(self):
        for arg in sys.argv:
            if arg == ADDON_ID:
                continue
            if arg.startswith('call='):
                self.call = arg[5:].lower()
            elif arg.startswith('?'):
                try:
                    params = dict(urllib.parse.parse_qsl(arg[1:]))
                    if 'call' in params:
                        self.call = params['call']
                        del params['call']
                    self.params.update(params)
                except:
                    pass
            else:
                try:
                    self.params[arg.split('=')[0].lower()] = '='.join(arg.split('=')[1:]).strip()
                except:
                    self.params[arg] = ''


def main():
    # Detecta se é plugin ou script
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        run_as_plugin(int(sys.argv[1]), sys.argv[2])
    else:
        Main()


if __name__ == '__main__':
    main()