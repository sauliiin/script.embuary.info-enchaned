# 🎬 Embuary Info Enhanced

<p align="center">
  <img src="resources/icon.png" alt="Embuary Info Logo" width="200"/>
</p>

<p align="center">
  <b>A powerful Kodi addon that provides rich metadata from TMDB, OMDB, and Trakt for movies, TV shows, and actors.</b>
</p>

<p align="center">
  <a href="#-features">Features</a> •
  <a href="#-installation">Installation</a> •
  <a href="#-service-properties">Service Properties</a> •
  <a href="#-plugin-modes">Plugin Modes</a> •
  <a href="#-listitem-properties">ListItem Properties</a> •
  <a href="#-skin-integration">Skin Integration</a>
</p>

---

## ✨ Features

- 🚀 **Adaptive Frequency Service** - Always-running background service that adjusts polling speed based on context
- 💾 **Multi-Layer Cache** - In-memory + SQLite + JSON cache for ultra-fast data retrieval
- 🔄 **IMDB ↔ TMDB Conversion** - Automatic ID conversion with persistent cache
- 👥 **Smart Cast Preloading** - Preloads actor data before you even open the info dialog
- 🎭 **Modular Data Loading** - Load only what you need (cast, crew, similar, etc.)
- 📊 **Extended Metadata** - Budget, Revenue, Awards, Ratings from multiple sources
- 🎬 **Trakt Reviews** - Integrated Trakt reviews with parallel fetching

---

## 📦 Installation

1. Download the latest release from the repository
2. Install via Kodi: **Add-ons → Install from zip file**
3. Configure your TMDB API key in addon settings
4. (Optional) Configure OMDB API key for extended ratings

---

## 🔧 Service Properties

The background service (`service.py`) automatically sets these properties on `Window(Home)` when you focus on items or open the video info dialog.

### Properties Set by Service

| Property | Description | Source | Example |
|----------|-------------|--------|---------|
| `budget` | Movie production budget | TMDB | `$150,000,000` |
| `revenue` | Movie box office revenue | TMDB | `$2,847,246,203` |
| `mpaa` | Content rating | TMDB | `PG-13`, `R`, `FSK 12` |
| `studio` | Production studios | TMDB | `Marvel Studios, Disney` |
| `country` | Production countries | TMDB | `United States, United Kingdom` |
| `awards` | Awards information | OMDB | `Won 3 Oscars. 89 wins & 178 nominations` |

### How to Use in Skins

```xml
<!-- Display budget in your skin -->
<label>Budget: $INFO[Window(Home).Property(budget)]</label>

<!-- Display awards -->
<label>$INFO[Window(Home).Property(awards)]</label>

<!-- Display MPAA rating -->
<label>Rated: $INFO[Window(Home).Property(mpaa)]</label>

<!-- Display studios -->
<label>Studio: $INFO[Window(Home).Property(studio)]</label>
```

### Service Contexts & Polling Intervals

The service uses **adaptive frequency** - it never stops, just slows down:

| Context | Interval | Description |
|---------|----------|-------------|
| `videoinfo` | 0.3s | DialogVideoInfo open - maximum speed |
| `home_active` | 0.3s | Home screen, no playback |
| `home_background` | 0.5s | Home with movie playing in background |
| `playing_osd` | 0.5s | OSD/SeekBar visible |
| `fullscreen` | 2.0s | Watching movie (keeps modules warm) |
| `idle` | 3.0s | No activity detected |

---

## 🔌 Plugin Modes

Call the plugin with different modes to get specific data:

### Cast Mode (Fastest)

```
plugin://script.embuary.info/?mode=cast&tmdb_id=550&type=movie
plugin://script.embuary.info/?mode=cast&imdb_id=tt0137523&type=movie
```

Returns a list of actors with:
- Name
- Character/Role
- Profile image

### Warmup Mode

```
plugin://script.embuary.info/?mode=warmup
```

Pre-loads heavy modules into memory to reduce cold-start time.

### Reset Scroll Mode

```
plugin://script.embuary.info/?mode=reset_scroll
```

Resets the actor panel scroll position (for skin animations).

---

## 🎭 ListItem Properties

When using the script dialogs or plugin, these properties are available on ListItems:

### Movie Properties

| Property | Description | Example |
|----------|-------------|---------|
| `id` | TMDB ID | `550` |
| `call` | Media type | `movie` |
| `role` | Actor's character | `Tyler Durden` |
| `budget` | Production budget | `$63,000,000` |
| `revenue` | Box office | `$100,853,753` |
| `homepage` | Official website | `https://...` |
| `file` | Local file path (if in library) | `/movies/...` |
| `collection` | Collection name | `The Dark Knight Collection` |
| `collection_id` | Collection TMDB ID | `263` |
| `collection_poster` | Collection poster URL | `https://image.tmdb.org/...` |
| `collection_fanart` | Collection fanart URL | `https://image.tmdb.org/...` |
| `region_release` | Regional release date | `2023-07-21` |
| `first_review_content` | Trakt reviews | `Great movie! [B]Nota: 9/10[/B]` |

### TV Show Properties

| Property | Description | Example |
|----------|-------------|---------|
| `id` | TMDB ID | `1399` |
| `call` | Media type | `tv` |
| `tvdb_id` | TVDB ID | `121361` |
| `TotalEpisodes` | Total episodes | `73` |
| `WatchedEpisodes` | Watched count (if in library) | `50` |
| `UnWatchedEpisodes` | Unwatched count | `23` |
| `homepage` | Official website | `https://...` |
| `lastepisode` | Last aired episode name | `The Iron Throne` |
| `lastepisode_plot` | Last episode plot | `...` |
| `lastepisode_number` | Last episode number | `6` |
| `lastepisode_season` | Last episode season | `8` |
| `lastepisode_date` | Last episode air date | `2019-05-19` |
| `lastepisode_thumb` | Last episode thumbnail | `https://image.tmdb.org/...` |
| `nextepisode` | Next episode name | `...` |
| `nextepisode_*` | Same as lastepisode_* | `...` |
| `first_review_content` | Trakt reviews | `Amazing show!` |

### Person Properties

| Property | Description | Example |
|----------|-------------|---------|
| `id` | TMDB ID | `287` |
| `call` | Type | `person` |
| `birthyear` | Birth year | `1963` |
| `birthday` | Birthday formatted | `1963-06-09` |
| `deathday` | Death day (if applicable) | `...` |
| `age` | Current age | `62` |
| `biography` | Biography text | `Bradley William Pitt is an...` |
| `place_of_birth` | Birthplace | `Shawnee, Oklahoma, USA` |
| `known_for_department` | Known for | `Acting` |
| `gender` | Gender | `male` / `female` |
| `LocalMovies` | Count of local movies | `15` |
| `LocalTVShows` | Count of local shows | `3` |
| `LocalMedia` | Total local media | `18` |

### Ratings Properties (OMDB)

| Property | Description | Example |
|----------|-------------|---------|
| `rating.metacritic` | Metacritic score | `66` |
| `rating.rotten` | Rotten Tomatoes critics | `79%` |
| `rating.rotten_avg` | RT critics average | `7.1/10` |
| `votes.rotten` | RT critics count | `354` |
| `rating.rotten_user` | RT audience score | `94%` |
| `rating.rotten_user_avg` | RT audience average | `4.3/5` |
| `votes.rotten_user` | RT audience count | `250000+` |
| `rating.imdb` | IMDB rating | `8.8` |
| `votes.imdb` | IMDB votes | `2,234,567` |
| `awards` | Awards summary | `Won 1 Oscar. 11 wins & 37 nominations` |
| `release` | DVD release date | `2024-03-15` |

### Studio Properties (Indexed)

```xml
<!-- Access multiple studios -->
$INFO[Container(10051).ListItem.Property(studio.0)]
$INFO[Container(10051).ListItem.Property(studio.icon.0)]
$INFO[Container(10051).ListItem.Property(studio.1)]
$INFO[Container(10051).ListItem.Property(studio.icon.1)]

<!-- Networks (for TV) -->
$INFO[Container(10051).ListItem.Property(network.0)]
$INFO[Container(10051).ListItem.Property(network.icon.0)]
```

---

## 🎨 Skin Integration

### Opening the Script Dialog

```xml
<!-- Open movie dialog -->
<onclick>RunScript(script.embuary.info,call=movie,tmdb_id=550)</onclick>

<!-- Open TV show dialog -->
<onclick>RunScript(script.embuary.info,call=tv,tmdb_id=1399)</onclick>

<!-- Open person dialog -->
<onclick>RunScript(script.embuary.info,call=person,tmdb_id=287)</onclick>

<!-- Search by query -->
<onclick>RunScript(script.embuary.info,call=movie,query=Fight Club)</onclick>
```

### Using Plugin for Cast Lists

```xml
<content>plugin://script.embuary.info/?mode=cast&amp;tmdb_id=$INFO[ListItem.UniqueID(tmdb)]&amp;type=movie</content>
```

### Container IDs in Dialog Windows

| Control ID | Content |
|------------|---------|
| `10051` | Main details (1 item) |
| `10052` | Cast list |
| `10053` | Similar movies/shows |
| `10054` | YouTube trailers |
| `10055` | Backdrops |
| `10056` | Crew list |
| `10057` | Collection items |
| `10058` | Seasons (TV only) |
| `10059` | Posters |

### Example: Accessing Cast in Skin

```xml
<control type="list" id="10052">
    <content>$INFO[Container(10052).ListItem.Label]</content>
    <itemlayout>
        <control type="image">
            <texture>$INFO[ListItem.Art(thumb)]</texture>
        </control>
        <control type="label">
            <label>$INFO[ListItem.Label]</label>  <!-- Actor name -->
        </control>
        <control type="label">
            <label>$INFO[ListItem.Label2]</label> <!-- Character name -->
        </control>
    </itemlayout>
</control>
```

---

## 📁 Project Structure

```
script.embuary.info/
├── addon.xml              # Addon manifest
├── default.py             # Main entry point (plugin + script modes)
├── service.py             # Background service (cast preloader)
└── resources/
    ├── lib/
    │   ├── async_loader.py    # Async cast loading with ThreadPool
    │   ├── cache_manager.py   # SQLite cache manager (singleton)
    │   ├── helper.py          # Utility functions
    │   ├── localdb.py         # Local Kodi library integration
    │   ├── main.py            # Dialog window management
    │   ├── omdb.py            # OMDB API integration
    │   ├── person.py          # Person/actor data handling
    │   ├── tmdb.py            # TMDB API + Trakt integration
    │   ├── video.py           # Movie/TV data handling
    │   └── widgets.py         # Widget/plugin content
    └── skins/
        └── default/1080i/
            ├── script-embuary-person.xml
            └── script-embuary-video.xml
```

---

## 🗃️ Cache System

### Three-Layer Cache Architecture

```
┌─────────────────────────────────────────────────┐
│  Layer 1: In-Memory Dict (fastest)              │
│  └── CastPreloader._cast_cache_memory           │
├─────────────────────────────────────────────────┤
│  Layer 2: SQLite Database (persistent)          │
│  └── cast_cache.db                              │
│      ├── cast_cache (TTL: 7 days)               │
│      └── imdb_tmdb_map (TTL: 30 days)           │
├─────────────────────────────────────────────────┤
│  Layer 3: JSON File Cache (legacy)              │
│  └── SimpleCache module                         │
└─────────────────────────────────────────────────┘
```

### Cache TTLs

| Cache Type | TTL | Location |
|------------|-----|----------|
| Cast data (memory) | Session | RAM |
| Cast data (SQLite) | 7 days | `cast_cache.db` |
| IMDB→TMDB map | 30 days | `cast_cache.db` |
| Trakt reviews | 30 days | `trakt_cache.json` |
| General TMDB data | 24 hours | SimpleCache |

---

## ⚙️ Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `tmdb_api_key` | Your TMDB API key | Required |
| `omdb_api_key` | OMDB API key (optional) | Optional |
| `similar_movies_filter` | Filter duplicates in similar | `true` |
| `filter_upcoming` | Hide unreleased content | `true` |
| `filter_daydelta` | Days to consider "upcoming" | `30` |
| `filter_movies` | Filter documentaries from filmography | `true` |
| `filter_shows` | Filter talk shows from filmography | `true` |

---

## 🔗 API Endpoints Used

### TMDB (The Movie Database)

- `/movie/{id}` - Movie details
- `/tv/{id}` - TV show details
- `/person/{id}` - Person details
- `/search/movie` - Movie search
- `/search/tv` - TV search
- `/search/person` - Person search
- `/find/{external_id}` - Find by IMDB/TVDB ID
- `/collection/{id}` - Collection details

### OMDB

- `/?i={imdb_id}` - Get ratings and awards

### Trakt

- `/movies/tmdb/{id}/comments` - Movie reviews
- `/shows/tmdb/{id}/comments` - TV reviews
- `/search/tmdb/{id}` - TMDB to Trakt slug conversion

---

## 📜 License

Apache-2.0

---

## 🙏 Credits

- Original script by [sualfred](https://github.com/sualfred/script.embuary.info)
- Enhanced by [sauliiin](https://github.com/sauliiin)
- TMDB for providing the movie database API
- OMDB for ratings data
- Trakt for reviews integration

---

<p align="center">
  Made with ❤️ for the Kodi community
</p>