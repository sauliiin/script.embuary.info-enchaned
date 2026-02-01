#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Módulo para buscar e formatar biografias dos atores do filme em reprodução.
Popular Window(Home).Property(ds_cast_bios) com texto formatado.
"""

import xbmc
import xbmcgui
import json
import time
from datetime import datetime, date
from threading import Thread, Lock

# Constantes
TMDB_API_KEY = "seu_api_key_aqui"  # Preencha com sua API key
TMDB_BASE_URL = "https://api.themoviedb.org/3"
CACHE_MAX_AGE = 86400 * 7  # 7 dias

# Cache em memória para biografias
_cast_bios_cache = {}
_cache_lock = Lock()


def calculate_age(birthday_str, deathday_str=None):
    """Calcula a idade baseada na data de nascimento."""
    if not birthday_str:
        return None
    try:
        birth_date = datetime.strptime(birthday_str, "%Y-%m-%d").date()
        if deathday_str:
            end_date = datetime.strptime(deathday_str, "%Y-%m-%d").date()
        else:
            end_date = date.today()
        
        age = end_date.year - birth_date.year
        if (end_date.month, end_date.day) < (birth_date.month, birth_date.day):
            age -= 1
        return age
    except:
        return None


def format_date_br(date_str):
    """Formata data para formato brasileiro DD/MM/YYYY."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except:
        return None


def get_person_details(person_id):
    """Busca detalhes de uma pessoa do TMDB."""
    cache_key = f"person_{person_id}"
    
    with _cache_lock:
        if cache_key in _cast_bios_cache:
            cached = _cast_bios_cache[cache_key]
            if time.time() - cached['ts'] < CACHE_MAX_AGE:
                return cached['data']
    
    try:
        from resources.lib.tmdb import tmdb_query
        details = tmdb_query(
            action='person',
            call=str(person_id),
            params={'language': 'pt-BR'}
        )
        
        if details:
            with _cache_lock:
                _cast_bios_cache[cache_key] = {
                    'data': details,
                    'ts': time.time()
                }
        return details
    except Exception as e:
        xbmc.log(f"[CastBios] Error fetching person {person_id}: {e}", xbmc.LOGWARNING)
        return None


def format_actor_bio(actor_name, person_details):
    """
    Formata a biografia de um ator no formato especificado.
    Exemplo: **Walter Scobel** possui 17 anos, nasceu em 06/01/2009 em Los Angeles, California, USA.
    """
    if not person_details:
        return None
    
    age = calculate_age(
        person_details.get('birthday'),
        person_details.get('deathday')
    )
    birthday_formatted = format_date_br(person_details.get('birthday'))
    place_of_birth = person_details.get('place_of_birth', '').strip() if person_details.get('place_of_birth') else None
    is_dead = person_details.get('deathday') is not None
    
    # Construir a frase
    parts = []
    
    # Nome em negrito
    parts.append(f"[B]{actor_name}[/B]")
    
    # Idade
    if age is not None:
        if is_dead:
            parts.append(f"tinha {age} anos quando faleceu")
        else:
            parts.append(f"possui {age} anos")
    
    # Data de nascimento
    if birthday_formatted:
        if age is not None:
            parts.append(f", nasceu em {birthday_formatted}")
        else:
            parts.append(f"nasceu em {birthday_formatted}")
    
    # Local de nascimento
    if place_of_birth:
        parts.append(f" em {place_of_birth}")
    
    # Juntar tudo
    if len(parts) > 1:
        bio = parts[0] + " " + "".join(parts[1:]) + "."
    else:
        bio = parts[0] + "."
    
    return bio


def get_movie_cast_from_player():
    """
    Obtém o cast do filme em reprodução via JSON-RPC.
    Retorna lista de dicionários com 'name' e 'tmdb_id' (se disponível).
    """
    try:
        # Primeiro, tenta obter o IMDB ID do filme em reprodução
        imdb_id = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
        title = xbmc.getInfoLabel('VideoPlayer.Title')
        year = xbmc.getInfoLabel('VideoPlayer.Year')
        
        if not imdb_id and not title:
            return []
        
        # Buscar no TMDB pelo IMDB ID ou título
        from resources.lib.tmdb import tmdb_query
        
        movie_details = None
        
        if imdb_id and imdb_id.startswith('tt'):
            # Busca por IMDB ID
            find_result = tmdb_query(
                action='find',
                call=imdb_id,
                params={'external_source': 'imdb_id'}
            )
            if find_result and find_result.get('movie_results'):
                tmdb_id = find_result['movie_results'][0]['id']
                movie_details = tmdb_query(
                    action='movie',
                    call=str(tmdb_id),
                    params={'append_to_response': 'credits', 'language': 'pt-BR'}
                )
        
        if not movie_details and title:
            # Busca por título
            search_result = tmdb_query(
                action='search',
                call='movie',
                params={'query': title, 'year': year if year else None}
            )
            if search_result and search_result.get('results'):
                tmdb_id = search_result['results'][0]['id']
                movie_details = tmdb_query(
                    action='movie',
                    call=str(tmdb_id),
                    params={'append_to_response': 'credits', 'language': 'pt-BR'}
                )
        
        if not movie_details:
            return []
        
        # Extrair cast
        credits = movie_details.get('credits', {})
        cast = credits.get('cast', [])
        
        # Retornar os primeiros 10 atores principais
        result = []
        for actor in cast[:10]:
            result.append({
                'name': actor.get('name', ''),
                'tmdb_id': actor.get('id'),
                'character': actor.get('character', '')
            })
        
        return result
        
    except Exception as e:
        xbmc.log(f"[CastBios] Error getting cast: {e}", xbmc.LOGWARNING)
        return []


def _generate_cast_bios_text(self, tmdb_id, media_type, max_actors=10):
    """
    Gera o texto completo com as biografias de todos os atores.
    Retorna string formatada com todas as bios separadas por quebra de linha dupla.
    """
    if not tmdb_id:
        return ""
    
    cast = self._get_movie_cast_from_tmdb(tmdb_id, media_type)
    
    if not cast:
        return ""
    
    bios = []
    
    for actor in cast[:max_actors]:
        if not actor.get('id'):
            continue
        
        person_details = self._get_person_details(actor['id'])
        if person_details:
            bio = self._format_actor_bio(actor['name'], person_details)
            if bio:
                bios.append(bio)
    
    # Juntar todas as bios com quebra de linha dupla (cada ator em linha separada com espaço)
    return "[CR][CR]".join(bios)


def update_cast_bios_property():
    """
    Atualiza a property Window(Home).Property(ds_cast_bios) com as biografias.
    Esta função deve ser chamada quando o OSD estiver visível durante playback.
    """
    try:
        win = xbmcgui.Window(10000)  # Home window
        
        # Verificar se está em playback de vídeo
        if not xbmc.Player().isPlayingVideo():
            win.clearProperty('ds_cast_bios')
            return
        
        # Gerar texto das biografias
        bios_text = generate_cast_bios_text(max_actors=10)
        
        if bios_text:
            win.setProperty('ds_cast_bios', bios_text)
            xbmc.log('[CastBios] Updated ds_cast_bios property', xbmc.LOGDEBUG)
        else:
            win.clearProperty('ds_cast_bios')
            
    except Exception as e:
        xbmc.log(f"[CastBios] Error updating property: {e}", xbmc.LOGWARNING)


def clear_cast_bios_property():
    """Limpa a property de biografias."""
    try:
        win = xbmcgui.Window(10000)
        win.clearProperty('ds_cast_bios')
    except:
        pass


class CastBiosUpdater(Thread):
    """Thread para atualizar biografias em background."""
    
    def __init__(self, callback=None):
        super(CastBiosUpdater, self).__init__()
        self.daemon = True
        self.callback = callback
        self._stop_event = False
    
    def run(self):
        """Executa a atualização das biografias."""
        try:
            update_cast_bios_property()
            if self.callback:
                self.callback()
        except Exception as e:
            xbmc.log(f"[CastBios] Thread error: {e}", xbmc.LOGWARNING)
    
    def stop(self):
        self._stop_event = True