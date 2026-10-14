from re import match
import asyncio

import discord
from discord.ext import commands
from soupsieve import match
import os
from dotenv import load_dotenv
from yt_dlp import YoutubeDL
import json
import random
import re

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)
with open("songs.json", "r") as f:
    playlist = json.load(f)

EG_OPTIONS = {
    "before_options": "-stream_loop -1",
    "options": "-vn",
}

@bot.event
async def setup_hook():
    await bot.tree.sync()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.hybrid_command(name="hello")
async def hello(ctx):
    await ctx.send("Halika!!! De fáj Trianon")
    

@bot.hybrid_command(name="play")
async def play(ctx, *, query: str):
    await ctx.defer()
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("Előbb csatlakozz egy hangcsatornához!")
        return

    query = query.strip().lower()
    if "http" in query:
        match = query
    else:
        match = next((url for name, url in playlist.items() if query in name.lower()), None)
        if match is None:
            await ctx.send(f"Nincs ilyen szám a playlistben: `{query}`")
            return

    voice_channel = ctx.author.voice.channel
    if ctx.voice_client is None:
        voice_client = await voice_channel.connect()
    else:
        voice_client = ctx.voice_client
        if voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)

    # yt-dlp resolves the YouTube URL to a direct streamable audio URL
    #os.system(f"yt-dlp -x --audio-format mp3 {match} -o {query}.mp3")

    if voice_client.is_playing():
        voice_client.stop()

    music_file = os.path.join(os.path.dirname(__file__), f"music/{query}.mp3")

    def playback_error(error):
        if error:
            print(f"Lejátszási hiba: {error!r}")

    voice_client.play(
        discord.FFmpegPCMAudio(music_file, **EG_OPTIONS),
        after=playback_error,
    )
    await ctx.send(f"Lejátszás: **{query}**")
@bot.hybrid_command(name="stop")
async def stop(ctx):
    if ctx.voice_client is not None and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Leállítva a lejátszást.")
    else:
        await ctx.send("Nincs lejátszás folyamatban.")
@bot.hybrid_command(name="pause")
async def pause(ctx):
    if ctx.voice_client is not None and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("Szüneteltetve a lejátszást.")
    else:
        await ctx.send("Nincs lejátszás folyamatban.")
@bot.hybrid_command(name="resume")
async def resume(ctx):
    if ctx.voice_client is not None and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("Folytatva a lejátszást.")
    else:
        await ctx.send("Nincs szüneteltetett lejátszás.")
@bot.hybrid_command(name="set-volume")
async def set_volume(ctx, volume: float):
    if ctx.voice_client is not None and ctx.voice_client.is_playing():
        ctx.voice_client.source.volume = max(0.0, min(volume, 1.0))
        await ctx.send(f"Hangerő beállítva: {ctx.voice_client.source.volume:.1f}")
    else:
        await ctx.send("Nincs lejátszás folyamatban.")
@bot.hybrid_command(name="leave")
async def leave(ctx):
    if ctx.voice_client is not None:
        await ctx.voice_client.disconnect()
        await ctx.send("Kilépve a hangcsatornából.")
    else:
        await ctx.send("Nem vagyok hangcsatornán.")
@bot.hybrid_command(name="p")
async def p(ctx, *, query: str):
    return await play.callback(ctx, query=query)
@bot.hybrid_command(name="download")
async def download(ctx, *, query: str):
    await ctx.defer()
    query = query.split(" ")
    url = query[0]
    alias = query[1]
    
    os.system(f"yt-dlp -x --audio-format mp3 {url} -o music/{alias}.mp3")
    playlist[alias] = alias
    with open("songs.json", "w") as f:
        json.dump(playlist, f, indent=4)
    await ctx.send(f"Letöltve: **{alias}**")
@bot.hybrid_command(name="r")
async def roll_dice(ctx,*,query: str):
    match = re.fullmatch(r"\s*(\d+)d(\d+)\s*([+-])?\s*(\d+)?\s*", query.lower())
    if match is None or (match.group(3) is None) != (match.group(4) is None):
        await ctx.send("Hibás dobás. Használat: `1d20`, `2d4 + 3` vagy `3d6 - 2`.")
        return

    num, die = map(int, match.group(1, 2))
    if die < 1:
        await ctx.send("A kocka oldalainak száma legalább 1 legyen.")
        return

    rolls = [random.randint(1, die) for _ in range(num)]
    modifier = int(match.group(4) or 0)
    if match.group(3) == "-":
        modifier *= -1
    total = sum(rolls) + modifier

    result = f"{num}d{die} ({', '.join(map(str, rolls))})"
    if match.group(3) is not None:
        result += f" {match.group(3)} {match.group(4)}"

    await ctx.send(
        f"{ctx.author.mention} 🎲\n"
        f"**Result:** {result}\n"
        f"**Total:** {total}"
    )
@bot.hybrid_command(name="takarodj")
async def takarodj(ctx):
    await leave.callback(ctx)
bot.run(os.getenv('DISCORD_TOKEN'))
