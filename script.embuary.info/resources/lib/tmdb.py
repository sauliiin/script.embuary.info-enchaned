#!/usr/bin/python
# coding: utf-8

########################

import xbmc
import xbmcgui
import xbmcvfs 
import requests
import datetime
from urllib.parse import urlencode
import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from resources.lib.helper import *
from resources.lib.omdb import *
from resources.lib.localdb import *

########################
'''
Poster (2:3)
w92 (92px × 138px), w154 (154px × 231px), w185 (185px × 278px), w342 (342px × 513px), w500 (500px × 750px), w780 (780px × 1170px), original

Backdrop/Fundo (16:9)
w300 (300px × 169px), w780 (780px × 439px), w1280 (1280px × 720px), original

Profile/Atores (2:3 vertical)
w45 (45px × 68px), w185 (185px × 278px), h632 (421px × 632px), original

Logo/Produtoras (varia)
w45 (45px × variável), w92 (92px × variável), w154 (154px × variável), w185 (185px × variável), w300 (300px × variável), w500 (500px × variável), original

Still/Frames de TV (16:9)
w92 (92px × 52px), w185 (185px × 104px), w300 (300px × 169px), original
'''

API_KEY = ADDON.getSettingString('tmdb_api_key')
API_URL = 'https://api.themoviedb.org/3/'

TMDB_IMG_BASE = 'https://image.tmdb.org/t/p/'
IMG_POSTER    = TMDB_IMG_BASE + 'w780'    
IMG_FANART    = TMDB_IMG_BASE + 'w1280'   
IMG_PROFILE   = TMDB_IMG_BASE + 'h632'     
IMG_STILL     = TMDB_IMG_BASE + 'w300'    
IMG_ORIGINAL  = TMDB_IMG_BASE + 'original' 

# Preferência: usar a chave configurada nas settings (consistente com settings.xml).
# Fallback: mantém a chave anterior caso a setting não exista/venha vazia.
TRAKT_API_KEY = ADDON.getSettingString('trakt_api_key') or 'fbc2791a2609e77d4e9d1689b7332a7124428eb7d8ea46085876d8867755a357'

CACHE_DIR = xbmcvfs.translatePath('special://profile/addon_data/script.embuary.info/')
CACHE_FILE = os.path.join(CACHE_DIR, 'trakt_cache.json')
CACHE_MAX_AGE = 30 * 24 * 60 * 60  # 30 dias em segundos

########################

session = requests.Session()

def tmdb_query(action,call=None,get=None,get2=None,get3=None,get4=None,params=None,use_language=True,language=DEFAULT_LANGUAGE,show_error=False):
    urlargs = {}
    urlargs['api_key'] = API_KEY

    if use_language:
        urlargs['language'] = language

    if params:
        urlargs.update(params)

    url = urljoin(API_URL ,action, call, get, get2, get3, get4)
    url = '{0}?{1}'.format(url, urlencode(urlargs))

    try:
        request = None

        for i in range(1,3): # loop if heavy server load (reduzido de 3 para 2 tentativas)
            try:
                request = session.get(url, timeout=3)
                if str(request.status_code).startswith('5'):
                    raise Exception(str(request.status_code))
                else:
                    break
            except Exception:
                xbmc.sleep(300)

        if not request or request.status_code == 404:
            error = ADDON.getLocalizedString(32019)
            raise Exception(error)

        elif request.status_code == 401:
            error = ADDON.getLocalizedString(32022)
            raise Exception(error)

        elif not request.ok:
            raise Exception('Code ' + str(request.status_code))

        result = request.json()

        if show_error:
            if len(result) == 0 or ('results' in result and not len(result['results']) == 0):
                error = ADDON.getLocalizedString(32019)
                raise Exception(error)

        return result

    except Exception as error:
        log('%s --> %s' % (error, url), ERROR)
        if show_error:
            tmdb_error(error)


def tmdb_search(call,query,year=None,include_adult='false'):
    if call == 'person':
        params = {'query': query, 'include_adult': include_adult}

    elif call == 'movie':
        params = {'query': query, 'year': year, 'include_adult': include_adult}

    elif call == 'tv':
        params = {'query': query, 'first_air_date_year': year}

    else:
        return ''

    result = tmdb_query(action='search',
                        call=call,
                        params=params)

    try:
        result = result.get('results')

        if not result:
            raise Exception

        return result

    except Exception:
        tmdb_error(ADDON.getLocalizedString(32019))


def tmdb_find(call,external_id,error_check=True):
    if external_id.startswith('tt'):
        external_source = 'imdb_id'
    else:
        external_source = 'tvdb_id'

    result = tmdb_query(action='find',
                        call=str(external_id),
                        params={'external_source': external_source},
                        use_language=False,
                        show_error=True
                        )
    try:
        if call == 'movie':
            return result.get('movie_results')
        else:
            return result.get('tv_results')

    except AttributeError:
        return

def tmdb_select_dialog(list,call):
    indexlist = []
    selectionlist = []

    if call == 'person':
        default_img = 'DefaultActor.png'
        img = 'profile_path'
        label = 'name'
        label2 = ''
        base_img = IMG_PROFILE

    elif call == 'movie':
        default_img = 'DefaultVideo.png'
        img = 'poster_path'
        label = 'title'
        label2 = 'tmdb_get_year(item.get("release_date", ""))'
        base_img = IMG_POSTER

    elif call == 'tv':
        default_img = 'DefaultVideo.png'
        img = 'poster_path'
        label = 'name'
        label2 = 'tmdb_get_year(item.get("first_air_date", ""))'
        base_img = IMG_POSTER

    else:
        return

    index = 0
    for item in list:
        icon = base_img + item[img] if item[img] is not None else ''
        list_item = xbmcgui.ListItem(item[label])
        list_item.setArt({'icon': default_img, 'thumb': icon})

        try:
            list_item.setLabel2(str(eval(label2)))
        except Exception:
            pass

        selectionlist.append(list_item)
        indexlist.append(index)
        index += 1

    busydialog(close=True)

    selected = DIALOG.select(xbmc.getLocalizedString(424), selectionlist, useDetails=True)

    if selected == -1:
        return -1

    busydialog()

    return indexlist[selected]


def tmdb_select_dialog_small(list):
    indexlist = []
    selectionlist = []

    index = 0
    for item in list:
        list_item = xbmcgui.ListItem(item)
        selectionlist.append(list_item)
        indexlist.append(index)
        index += 1

    busydialog(close=True)

    selected = DIALOG.select(xbmc.getLocalizedString(424), selectionlist, useDetails=False)

    if selected == -1:
        return -1

    busydialog()

    return indexlist[selected]


def tmdb_calc_age(birthday,deathday=None):
    if deathday is not None:
        ref_day = deathday.split("-")

    elif birthday:
        date = datetime.date.today()
        ref_day = [date.year, date.month, date.day]

    else:
        return ''

    born = birthday.split('-')
    age = int(ref_day[0]) - int(born[0])

    if len(born) > 1:
        diff_months = int(ref_day[1]) - int(born[1])
        diff_days = int(ref_day[2]) - int(born[2])

        if diff_months < 0 or (diff_months == 0 and diff_days < 0):
            age -= 1

    return age


def tmdb_error(message=ADDON.getLocalizedString(32019)):
    busydialog(close=True)
    DIALOG.ok(ADDON.getLocalizedString(32000), str(message))


def tmdb_studios(list_item,item,key):
    if key == 'production':
        key_name = 'production_companies'
        prop_name = 'studio'
    elif key == 'network':
        key_name = 'networks'
        prop_name = 'network'
    else:
        return

    i = 0
    for studio in item[key_name]:
        icon = IMG_STILL + studio['logo_path'] if studio['logo_path'] is not None else ''
        if icon:
            list_item.setProperty(prop_name + '.' + str(i), studio['name'])
            list_item.setProperty(prop_name + '.icon.' + str(i), icon)
            i += 1


def tmdb_check_localdb(local_items,title,originaltitle,year,imdbnumber=False):
    found_local = False
    local = {'dbid': -1, 'playcount': 0, 'watchedepisodes': '', 'episodes': '', 'unwatchedepisodes': '', 'file': ''}

    if local_items:
        for item in local_items:
            dbid = item['dbid']
            playcount = item['playcount']
            episodes = item.get('episodes', '')
            watchedepisodes = item.get('watchedepisodes', '')
            file = item.get('file', '')

            if imdbnumber and item['imdbnumber'] == imdbnumber:
                found_local = True
                break

            try:
                tmdb_year = int(tmdb_get_year(year))
                item_year = int(item['year'])

                if item_year == tmdb_year:
                    if item['originaltitle'] == originaltitle or item['title'] == originaltitle or item['title'] == title:
                        found_local = True
                        break
                elif tmdb_year in [item_year-2, item_year-1, item_year+1, item_year+2]:
                    if item['title'] == title and item['originaltitle'] == originaltitle:
                        found_local = True
                        break

            except ValueError:
                pass

    if found_local:
        local['dbid'] = dbid
        local['file'] = file
        local['playcount'] = playcount
        local['episodes'] = episodes
        local['watchedepisodes'] = watchedepisodes
        local['unwatchedepisodes'] = episodes - watchedepisodes if episodes else ''

    return local


def tmdb_handle_person(item):
    if item.get('gender') == 2:
        gender = 'male'
    elif item.get('gender') == 1:
        gender = 'female'
    else:
        gender = ''

    icon = IMG_PROFILE + item['profile_path'] if item['profile_path'] is not None else ''
    list_item = xbmcgui.ListItem(label=item['name'])
    list_item.setProperty('birthyear', date_year(item.get('birthday', '')))
    list_item.setProperty('birthday', date_format(item.get('birthday', '')))
    list_item.setProperty('deathday', date_format(item.get('deathday', '')))
    list_item.setProperty('age', str(tmdb_calc_age(item.get('birthday', ''), item.get('deathday'))))
    list_item.setProperty('biography', tmdb_fallback_info(item, 'biography'))
    list_item.setProperty('place_of_birth', item.get('place_of_birth').strip() if item.get('place_of_birth') else '')
    list_item.setProperty('known_for_department', item.get('known_for_department', ''))
    list_item.setProperty('gender', gender)
    list_item.setProperty('id', str(item.get('id', '')))
    list_item.setProperty('call', 'person')
    list_item.setArt({'icon': 'DefaultActor.png', 'thumb': icon, 'poster': icon})

    return list_item

# =======================
# CACHE PERSISTENTE TRAKT
# =======================

def _load_trakt_cache():
    if not os.path.exists(CACHE_FILE):
        return {'slug_map': {}, 'reviews': {}}
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        now = time.time()
        for section in ['slug_map', 'reviews']:
            old_keys = []
            for k, v in data.get(section, {}).items():
                ts = v['ts'] if isinstance(v, dict) and 'ts' in v else 0
                if ts and now - ts > CACHE_MAX_AGE:
                    old_keys.append(k)
            for k in old_keys:
                del data[section][k]
        return data
    except Exception as e:
        xbmc.log(f"[Trakt] Error loading cache: {str(e)}", xbmc.LOGDEBUG)
        return {'slug_map': {}, 'reviews': {}}

def _save_trakt_cache(cache):
    try:
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        xbmc.log(f"[Trakt] Error saving cache: {str(e)}", xbmc.LOGDEBUG)

TRAKT_CACHE = _load_trakt_cache()

def clear_trakt_cache():
    global TRAKT_CACHE
    TRAKT_CACHE = {'slug_map': {}, 'reviews': {}}
    _save_trakt_cache(TRAKT_CACHE)

def _set_cache(section, key, value):
    now = time.time()
    if not isinstance(value, dict):
        value = {'value': value, 'ts': now}
    else:
        value['ts'] = now
    TRAKT_CACHE[section][key] = value
    _save_trakt_cache(TRAKT_CACHE)

def _get_cache(section, key):
    entry = TRAKT_CACHE.get(section, {}).get(key)
    if not entry:
        return None
    if isinstance(entry, dict) and 'value' in entry:
        ts = entry.get('ts', 0)
        if ts and time.time() - ts > CACHE_MAX_AGE:
            del TRAKT_CACHE[section][key]
            _save_trakt_cache(TRAKT_CACHE)
            return None
        return entry['value']
    return entry

def trakt_get_slug_from_tmdb_id(item_id, media_type='movie'):
    cache_key = f"{media_type}_{item_id}"
    cached = _get_cache('slug_map', cache_key)
    if cached is not None:
        return cached

    if not str(item_id).isdigit():
        _set_cache('slug_map', cache_key, str(item_id))
        return str(item_id)

    url = f"https://api.trakt.tv/search/tmdb/{item_id}?type={media_type}"
    headers = {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': TRAKT_API_KEY
    }

    try:
        response = session.get(url, headers=headers, timeout=1)
        if response.status_code == 200:
            results = response.json()
            if results:
                slug = results[0].get(media_type, {}).get('ids', {}).get('slug')
                if slug:
                    _set_cache('slug_map', cache_key, slug)
                    return slug
    except Exception as e:
        xbmc.log(f"[Trakt] Error getting slug: {str(e)}", xbmc.LOGDEBUG)

    _set_cache('slug_map', cache_key, None)
    return None

def tmdb_get_combined_reviews(item_id, media_type='movie', max_comments=20):
    cache_key = f"{media_type}_{item_id}"
    cached = _get_cache('reviews', cache_key)
    if cached is not None:
        return cached

    trakt_type = 'movies' if media_type == 'movie' else 'shows'
    headers = {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': TRAKT_API_KEY
    }
    params = {'limit': 200, 'sort': 'likes'}

    def fmt(c):
        comment_text = c.get('comment', '').replace('\n', ' ').strip()
        is_spoiler = c.get('spoiler', False)
        user_lang = c.get('user', {}).get('language', 'en')
        
        if is_spoiler or len(comment_text) > 600 or user_lang not in ('pt', 'en', 'es'):
            return None

        review_block = f"[B][COLOR FFE50914]ANÁLISE:[/COLOR][/B] {comment_text}"
        user_rating = c.get('user_rating')
        if user_rating is not None:
             review_block += f"  [B]NOTA: {user_rating}/10[/B]"
             
        return review_block

    comments = []
    if str(item_id).isdigit():
        url = f"https://api.trakt.tv/{trakt_type}/tmdb/{item_id}/comments"
        try:
            response = session.get(url, headers=headers, params=params, timeout=1)
            if response.status_code == 200:
                data = response.json()
                # Apply filter and limit
                valid_comments = []
                for c in data:
                    formatted = fmt(c)
                    if formatted:
                        valid_comments.append(formatted)
                        if len(valid_comments) >= 20: break
                comments = valid_comments
        except Exception as e:
            xbmc.log(f"[Trakt] Error getting reviews by TMDB id: {str(e)}", xbmc.LOGDEBUG)

        if not comments:
            slug = trakt_get_slug_from_tmdb_id(item_id, media_type)
            if slug and slug != str(item_id):
                url = f"https://api.trakt.tv/{trakt_type}/{slug}/comments"
                try:
                    response = session.get(url, headers=headers, params=params, timeout=1)
                    if response.status_code == 200:
                        data = response.json()
                        valid_comments = []
                        for c in data:
                            formatted = fmt(c)
                            if formatted:
                                valid_comments.append(formatted)
                                if len(valid_comments) >= 20: break
                        comments = valid_comments
                except Exception as e:
                    xbmc.log(f"[Trakt] Error getting reviews by slug: {str(e)}", xbmc.LOGDEBUG)
    else:
        url = f"https://api.trakt.tv/{trakt_type}/{item_id}/comments"
        try:
            response = session.get(url, headers=headers, params=params, timeout=1)
            if response.status_code == 200:
                data = response.json()
                valid_comments = []
                for c in data:
                    formatted = fmt(c)
                    if formatted:
                        valid_comments.append(formatted)
                        if len(valid_comments) >= 20: break
                comments = valid_comments
        except Exception as e:
            xbmc.log(f"[Trakt] Error getting reviews by slug: {str(e)}", xbmc.LOGDEBUG)

    result = '\n\n'.join(comments) if comments else ''
    _set_cache('reviews', cache_key, result)
    return result

def tmdb_get_combined_reviews_parallel(item_ids, media_type='movie', max_comments=10):
    futures = {}
    results = {}

    def get_reviews(item_id):
        return tmdb_get_combined_reviews(item_id, media_type, max_comments)

    with ThreadPoolExecutor(max_workers=20) as executor:
        for item_id in item_ids:
            futures[executor.submit(get_reviews, item_id)] = item_id
        for future in as_completed(futures):
            item_id = futures[future]
            try:
                results[item_id] = future.result()
            except Exception as e:
                results[item_id] = ''
                xbmc.log(f"[Trakt] Error in parallel review fetch for {item_id}: {str(e)}", xbmc.LOGDEBUG)
    return results


def tmdb_handle_movie(item, local_items=None, full_info=False, mediatype='movie', fetch_reviews=False):
    icon = IMG_POSTER + item['poster_path'] if item['poster_path'] is not None else ''
    backdrop = IMG_FANART + item['backdrop_path'] if item['backdrop_path'] is not None else ''

    label = item['title'] or item['original_title']
    originaltitle = item.get('original_title', '')
    imdbnumber = item.get('imdb_id', '')
    collection = item.get('belongs_to_collection', '')
    duration = item.get('runtime', 0) * 60 if item.get('runtime', 0) > 0 else ''

    premiered = item.get('release_date')
    if premiered in ['2999-01-01', '1900-01-01']:
        premiered = ''

    local_info = tmdb_check_localdb(local_items, label, originaltitle, premiered, imdbnumber)
    dbid = local_info['dbid']
    is_local = True if dbid > 0 else False

    list_item = xbmcgui.ListItem(label=label)
    list_item.setInfo('video', {
        'title': label,
        'originaltitle': originaltitle,
        'dbid': dbid,
        'playcount': local_info['playcount'],
        'imdbnumber': imdbnumber,
        'rating': item.get('vote_average', ''),
        'votes': item.get('vote_count', ''),
        'premiered': premiered,
        'mpaa': tmdb_get_cert(item),
        'tagline': item.get('tagline', ''),
        'duration': duration,
        'status': item.get('status', ''),
        'plot': tmdb_fallback_info(item, 'overview'),
        'director': tmdb_join_items_by(item.get('crew', ''), key_is='job', value_is='Director'),
        'writer': tmdb_join_items_by(item.get('crew', ''), key_is='department', value_is='Writing'),
        'country': tmdb_join_items(item.get('production_countries', '')),
        'genre': tmdb_join_items(item.get('genres', '')),
        'studio': tmdb_join_items(item.get('production_companies', '')),
        'mediatype': mediatype
    })
    list_item.setArt({'icon': 'DefaultVideo.png', 'thumb': icon, 'poster': icon, 'fanart': backdrop})
    list_item.setProperty('role', item.get('character', ''))
    list_item.setProperty('budget', format_currency(item.get('budget')))
    list_item.setProperty('revenue', format_currency(item.get('revenue')))
    list_item.setProperty('homepage', item.get('homepage', ''))
    list_item.setProperty('file', local_info.get('file', ''))
    list_item.setProperty('id', str(item.get('id', '')))
    list_item.setProperty('call', 'movie')

    if full_info:
        tmdb_studios(list_item, item, 'production')
        omdb_properties(list_item, imdbnumber)

        region_release = tmdb_get_region_release(item)
        if premiered != region_release:
            list_item.setProperty('region_release', date_format(region_release))

        if collection:
            list_item.setProperty('collection', collection['name'])
            list_item.setProperty('collection_id', str(collection['id']))
            list_item.setProperty('collection_poster',
                                  IMG_POSTER + collection['poster_path'] if collection['poster_path'] is not None else '')
            list_item.setProperty('collection_fanart',
                                  IMG_FANART + collection['backdrop_path'] if collection['backdrop_path'] is not None else '')

    if fetch_reviews and item.get('id'):
        combined_review = tmdb_get_combined_reviews(item['id'], media_type='movie')
        list_item.setProperty('first_review_content', combined_review)
    
    # Seta budget, revenue e MPAA na Window(Home) para acesso no DialogVideoInfo
    winprop('budget', format_currency(item.get('budget')))
    winprop('revenue', format_currency(item.get('revenue')))
    mpaa = tmdb_get_cert(item)
    if mpaa:
        winprop('mpaa', mpaa)

    return list_item, is_local


def tmdb_handle_tvshow(item, local_items=None, full_info=False, mediatype='tv', fetch_reviews=False):
    icon = IMG_POSTER + item['poster_path'] if item['poster_path'] is not None else ''
    backdrop = IMG_FANART + item['backdrop_path'] if item['backdrop_path'] is not None else ''

    label = item['name'] or item['original_name']
    originaltitle = item.get('original_name', '')
    imdbnumber = item.get('external_ids', {}).get('imdb_id', '')
    next_episode = item.get('next_episode_to_air', '')
    last_episode = item.get('last_episode_to_air', '')
    tvdb_id = item.get('external_ids', {}).get('tvdb_id', '')

    premiered = item.get('first_air_date')
    if premiered in ['2999-01-01', '1900-01-01']:
        premiered = ''

    local_info = tmdb_check_localdb(local_items, label, originaltitle, premiered, tvdb_id)
    dbid = local_info['dbid']
    is_local = True if dbid > 0 else False

    list_item = xbmcgui.ListItem(label=label)
    list_item.setInfo('video', {
        'title': label,
        'originaltitle': originaltitle,
        'dbid': dbid,
        'playcount': local_info['playcount'],
        'status': item.get('status', ''),
        'rating': item.get('vote_average', ''),
        'votes': item.get('vote_count', ''),
        'imdbnumber': imdbnumber,
        'premiered': premiered,
        'mpaa': tmdb_get_cert(item),
        'season': str(item.get('number_of_seasons', '')),
        'episode': str(item.get('number_of_episodes', '')),
        'plot': tmdb_fallback_info(item, 'overview'),
        'director': tmdb_join_items(item.get('created_by', '')),
        'genre': tmdb_join_items(item.get('genres', '')),
        'studio': tmdb_join_items(item.get('networks', '')),
        'mediatype': mediatype
    })
    list_item.setArt({'icon': 'DefaultVideo.png', 'thumb': icon, 'poster': icon, 'fanart': backdrop})
    list_item.setProperty('TotalEpisodes', str(local_info['episodes']))
    list_item.setProperty('WatchedEpisodes', str(local_info['watchedepisodes']))
    list_item.setProperty('UnWatchedEpisodes', str(local_info['unwatchedepisodes']))
    list_item.setProperty('homepage', item.get('homepage', ''))
    list_item.setProperty('role', item.get('character', ''))
    list_item.setProperty('tvdb_id', str(tvdb_id))
    list_item.setProperty('id', str(item.get('id', '')))
    list_item.setProperty('call', 'tv')

    if full_info:
        tmdb_studios(list_item, item, 'production')
        tmdb_studios(list_item, item, 'network')
        omdb_properties(list_item, imdbnumber)

        if last_episode:
            list_item.setProperty('lastepisode', last_episode.get('name'))
            list_item.setProperty('lastepisode_plot', last_episode.get('overview'))
            list_item.setProperty('lastepisode_number', str(last_episode.get('episode_number')))
            list_item.setProperty('lastepisode_season', str(last_episode.get('season_number')))
            list_item.setProperty('lastepisode_date', date_format(last_episode.get('air_date')))
            list_item.setProperty('lastepisode_thumb',
                                  IMG_STILL + last_episode['still_path'] if last_episode['still_path'] is not None else '')

        if next_episode:
            list_item.setProperty('nextepisode', next_episode.get('name'))
            list_item.setProperty('nextepisode_plot', next_episode.get('overview'))
            list_item.setProperty('nextepisode_number', str(next_episode.get('episode_number')))
            list_item.setProperty('nextepisode_season', str(next_episode.get('season_number')))
            list_item.setProperty('nextepisode_date', date_format(next_episode.get('air_date')))
            list_item.setProperty('nextepisode_thumb',
                                  IMG_STILL + next_episode['still_path'] if next_episode['still_path'] is not None else '')

    if fetch_reviews and item.get('id'):
        combined_review = tmdb_get_combined_reviews(item['id'], media_type='tv')
        list_item.setProperty('first_review_content', combined_review)

    return list_item, is_local



def tmdb_handle_season(item,tvshow_details,full_info=False):
    backdrop = IMG_FANART + tvshow_details['backdrop_path'] if tvshow_details['backdrop_path'] is not None else ''
    icon = IMG_POSTER + item['poster_path'] if item['poster_path'] is not None else ''
    if not icon and tvshow_details['poster_path']:
        icon = IMG_POSTER + tvshow_details['poster_path']

    imdbnumber = tvshow_details['external_ids']['imdb_id'] if tvshow_details.get('external_ids') else ''
    season_nr = str(item.get('season_number', ''))
    tvshow_label = tvshow_details['name'] or tvshow_details['original_name']

    episodes_count = len(item.get('episodes', []))

    list_item = xbmcgui.ListItem(label=tvshow_label)
    list_item.setInfo('video', {'title': item['name'],
                                'tvshowtitle': tvshow_label,
                                'premiered': item.get('air_date', ''),
                                'episode': episodes_count,
                                'season': season_nr,
                                'plot': item.get('overview', ''),
                                'genre': tmdb_join_items(tvshow_details.get('genres', '')),
                                'rating': tvshow_details.get('vote_average', ''),
                                'votes': tvshow_details.get('vote_count', ''),
                                'mpaa': tmdb_get_cert(tvshow_details),
                                'mediatype': 'season'}
                                )
    list_item.setArt({'icon': 'DefaultVideo.png', 'thumb': icon, 'poster': icon, 'fanart': backdrop})
    list_item.setProperty('TotalEpisodes', str(episodes_count))
    list_item.setProperty('id', str(tvshow_details['id']))
    list_item.setProperty('call', 'tv')
    list_item.setProperty('call_season', season_nr)

    if full_info:
        tmdb_studios(list_item,tvshow_details, 'production')
        tmdb_studios(list_item,tvshow_details, 'network')
        omdb_properties(list_item, imdbnumber)

    return list_item


def tmdb_fallback_info(item,key):
    if FALLBACK_LANGUAGE == DEFAULT_LANGUAGE:
        try:
            key_value = item.get(key, '').replace('&amp;', '&').strip()
        except Exception:
            key_value = ''
    else:
        key_value = tmdb_get_translation(item, key, DEFAULT_LANGUAGE)

    if not key_value:
        key_value = tmdb_get_translation(item, key, FALLBACK_LANGUAGE)

    return key_value


def tmdb_get_translation(item,key,language):
    key_value_iso_639_1 = ""
    try:
        language_iso_639_1 = language[:2]
        language_iso_3166_1 = language[3:] if len(language)>3 else None

        for translation in item['translations']['translations']:
            if translation.get('iso_639_1') == language_iso_639_1 and translation['data'][key]:
                key_value = translation['data'][key]
                if key_value:
                    key_value = key_value.replace('&amp;', '&').strip()
                    if not language_iso_3166_1 or language_iso_3166_1 == translation.get('iso_3166_1'):
                        return key_value
                    else:
                        key_value_iso_639_1 = key_value
    except Exception:
        pass

    return key_value_iso_639_1


def tmdb_handle_images(item):
    icon = IMG_ORIGINAL + item['file_path'] if item['file_path'] is not None else ''
    list_item = xbmcgui.ListItem(label=str(item['width']) + 'x' + str(item['height']) + 'px')
    list_item.setArt({'icon': 'DefaultPicture.png', 'thumb': icon})
    list_item.setProperty('call', 'image')

    return list_item


def tmdb_handle_credits(item):
    icon = IMG_PROFILE + item['profile_path'] if item['profile_path'] is not None else ''
    list_item = xbmcgui.ListItem(label=item['name'])
    list_item.setLabel2(item['label2'])
    list_item.setArt({'icon': 'DefaultActor.png', 'thumb': icon, 'poster': icon})
    list_item.setProperty('id', str(item.get('id', '')))
    list_item.setProperty('call', 'person')

    return list_item


def tmdb_handle_yt_videos(item):
    icon = 'https://img.youtube.com/vi/%s/0.jpg' % str(item['key'])
    list_item = xbmcgui.ListItem(label=item['name'])
    list_item.setLabel2(item.get('type', ''))
    list_item.setArt({'icon': 'DefaultVideo.png', 'thumb': icon, 'landscape': icon})
    list_item.setProperty('ytid', str(item['key']))
    list_item.setProperty('call', 'youtube')

    return list_item


def tmdb_join_items_by(item,key_is,value_is,key='name'):
    values = []
    for value in item:
        if value[key_is] == value_is:
            values.append(value[key])
    return get_joined_items(values)


def tmdb_join_items(item,key='name'):
    values = []
    for value in item:
        values.append(value[key])
    return get_joined_items(values)


def tmdb_get_year(item):
    try:
        year = str(item)[:-6]
        return year
    except Exception:
        return ''


def tmdb_get_region_release(item):
    try:
        for release in item['release_dates']['results']:
            if release['iso_3166_1'] == COUNTRY_CODE:
                date = release['release_dates'][0]['release_date']
                return date[:-14]
    except Exception:
        return ''


def tmdb_get_cert(item):
    prefix = 'FSK ' if COUNTRY_CODE == 'DE' else ''
    mpaa = ''
    mpaa_fallback = ''

    # Mapeamento de Classificação para o Padrão Brasileiro
    CERT_MAP_BR = {
        # USA
        'G': 'Livre',
        'PG': '10 anos',
        'PG-13': '12 anos',
        'R': '16 anos',
        'NC-17': '18 anos',
        'NR': 'Livre',
        'Unrated': 'Livre',
        # Portugal e Europa
        'M/3': 'Livre',
        'M/4': 'Livre',
        'M/6': 'Livre',
        'M/12': '12 anos',
        'M/14': '14 anos',
        'M/16': '16 anos',
        'M/18': '18 anos',
        'Públicos': 'Livre',
        # Numeric BR (Native)
        '10': '10 anos',
        '12': '12 anos',
        '14': '14 anos',
        '16': '16 anos',
        '18': '18 anos',
        'L': 'Livre'
    }

    if item.get('content_ratings'):
        for cert in item['content_ratings']['results']:
            if cert['iso_3166_1'] == COUNTRY_CODE:
                mpaa = cert['rating']
                break
            elif cert['iso_3166_1'] == 'US':
                mpaa_fallback = cert['rating']

    elif item.get('release_dates'):
        for cert in item['release_dates']['results']:
            if cert['iso_3166_1'] == COUNTRY_CODE:
                mpaa = cert['release_dates'][0]['certification']
                break
            elif cert['iso_3166_1'] == 'US':
                mpaa_fallback = cert['release_dates'][0]['certification']

    final_cert = mpaa if mpaa else mpaa_fallback
    
    # Aplica Tradução (apenas se for código BR ou fallback)
    # Se já vier "10", "12" etc do próprio TMDB BR, o mapa mantém (se não achar key, retorna default)
    if final_cert:
         final_cert = CERT_MAP_BR.get(final_cert, final_cert)

    if final_cert:
        return prefix + final_cert
    return ''


def omdb_properties(list_item,imdbnumber):
    if OMDB_API_KEY and imdbnumber:
        omdb = omdb_api(imdbnumber)
        if omdb:
            list_item.setProperty('rating.metacritic', omdb.get('metacritic', ''))
            list_item.setProperty('rating.rotten', omdb.get('tomatometerallcritics', ''))
            list_item.setProperty('rating.rotten_avg', omdb.get('tomatometerallcritics_avg', ''))
            list_item.setProperty('votes.rotten', omdb.get('tomatometerallcritics_votes', ''))
            list_item.setProperty('rating.rotten_user', omdb.get('tomatometerallaudience', ''))
            list_item.setProperty('rating.rotten_user_avg', omdb.get('tomatometerallaudience_avg', ''))
            list_item.setProperty('votes.rotten_user', omdb.get('tomatometerallaudience_votes', ''))
            list_item.setProperty('rating.imdb', omdb.get('imdbRating', ''))
            list_item.setProperty('votes.imdb', omdb.get('imdbVotes', ''))
            list_item.setProperty('awards', omdb.get('awards', ''))
            list_item.setProperty('release', omdb.get('DVD', ''))
            
            # Seta awards na Window(Home) para acesso no DialogVideoInfo
            awards = omdb.get('awards', '')
            if awards:
                winprop('awards', awards)