# Gyulus

Discord zenebot (discord.py). A zenéket egy S3-kompatibilis tárhelyről (Cloudflare R2) streameli. A YouTube-letöltést egy külön, otthoni gépen futó worker végzi, mert a bot-hostingok IP-jét a YouTube gyakran blokkolja.

## Felépítés

| Fájl | Szerep |
|------|--------|
| `main.py` | Bot indítása, Cogok betöltése, parancsok szinkronizálása |
| `cogs/general.py` | `/hello`, `/r` (dobókocka) |
| `cogs/music.py` | Zenelejátszás, zenetár, letöltés kérése |
| `cogs/greeting.py` | Időzített esküvői köszöntés |
| `cogs/ai.py` | Csatornaüzenetek AI-összefoglalása |
| `storage.py` | S3/R2 réteg (listázás, feltöltés, presigned URL, takarítás, job-sor) |
| `downloader.py`, `worker.py` | yt-dlp letöltő worker (otthoni gépen fut) |

## Parancsok

| Parancs | Leírás |
|---------|--------|
| `/play <név/link/keresés>` | Zenetárból névrészlet alapján játszik. YouTube linket letölt (ideiglenesen), ha nem link és nincs találat, az első YouTube-találatot tölti le |
| `/p` | A `/play` rövidítése |
| `/setloop True/False` | True (alap): a szám ismétlődik. False: a szám végén véletlen szám indul a zenetárból |
| `/skip` | Következő véletlen szám a zenetárból |
| `/stop`, `/pause`, `/resume` | Lejátszás vezérlése |
| `/set-volume <0.0–1.0>` | Hangerő |
| `/leave`, `/takarodj` | A bot elhagyja a hangcsatornát |
| `/download` | Letöltés és feltöltés a zenetárba |
| `/hello` | Köszönés |
| `/r 1d20` | Dobókocka |
| `/summary 17:05 [19:00]` | A csatorna üzeneteinek összefoglalása a kezdő időponttól, opcionálisan egy záró időpontig |
| `/summary 2026-11-10 [2026-11-11]` | Egy nap vagy a kezdő és záró dátum közötti teljes napok összefoglalása |

## Működés

- A zenetár a bucket `temp/` és `jobs/` előtag nélküli MP3 fájljai.
- YouTube linknél a bot egy `jobs/<id>.job` fájlt ír a bucketbe. A worker letölti az MP3-at, feltölti `temp/` alá, és `jobs/<id>.result`-ot ír. A bot legfeljebb 3 percig vár.
- Az ideiglenes (`temp/`) fájlokat a bot 1 óra után törli.
- A `/setloop` és a hangerő szerverenként, memóriában tárolódik, újraindításkor visszaáll.
- A `/summary` hosszabb időszakra részletesebb választ kér az AI-tól. Az időpont a bot gépének helyi ideje; ha még nem érkezett el, az előző napra vonatkozik. A válasz legfeljebb egy, 4096 karakteres Discord-embed; hosszabb időszakok több API-tokent és magasabb költséget jelenthetnek.
- Időpontként például `17`, `17:05` vagy `17.05` adható meg. A `/summary 17 19` a legutóbbi lezárult 17–19 óra közötti időszakot összegzi; a kezdő időpontot beleveszi, a záró időpontot nem. Az időszak átnyúlhat éjfélen; azonos kezdő és záró időpont 24 órát jelent.
- Dátumként `2026-11-10` vagy `2026.11.10` használható. Záró dátum nélkül a megadott napot, záró dátummal mindkét napot és a köztük lévő napokat is összegzi, a bot gépének helyi ideje szerint. A mai napból a már eltelt időt veszi figyelembe; jövőbeli vagy fordított dátumtartomány és dátum/időpont keverése nem megengedett.
- A Discord slash parancs `since` és `end` mezői a legutóbbi hét nap dátumait és egész órákat javasolnak; más érvényes értékeket is be lehet írni.
- Az összefoglaló a jelenlegi szerverbeceneveket használja; becenév hiányában a Discord-megjelenített név, majd a felhasználónév szerepel. Az említések is megjelenített névvé alakulnak, ha a Discord fel tudja oldani őket.
- Az összefoglaló utasítást kap arra, hogy Gyulust a botként, saját magaként értelmezze; a botnak címzett Discord-említéseket azonosító alapján külön megjelöli.

## Telepítés (bot)

Követelmények: Python 3.12+, ffmpeg.

```
pip install -r requirements.txt
copy .env.example .env   # majd töltsd ki
python main.py
```

Környezeti változók (`.env`):

- `DISCORD_TOKEN`, `NANDRIS_USER_ID`, `GREETING_CHANNEL_ID`
- `OPENAI_API_KEY` (a `/summary` parancshoz; a GPT-6 Luna API használata díjköteles lehet)
- `S3_ENDPOINT_URL` (bucketnév nélkül), `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, `S3_REGION` (R2-nél `auto`)

## Telepítés (letöltő worker, otthoni gépen)

Követelmények: Python, ffmpeg.

```
pip install -r requirements-worker.txt
python worker.py
```

A worker ugyanazt a `.env`-et használja (S3_* értékek). Opcionálisan a `YTDLP_COOKIES_FILE` egy Netscape formátumú YouTube süti fájlra mutat. Ha a worker nem fut, a YouTube-letöltések időtúllépéssel hibáznak, a zenetárból való lejátszás viszont működik.

## Biztonság

A `.env` és a `cookies/` mappa nem kerülhet verziókezelés alá (a `.gitignore` tartalmazza őket). Ha egy kulcs kiszivárgott, cseréld le az R2 API tokent.
