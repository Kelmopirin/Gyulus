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
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.command(name="hello")
async def hello(ctx):
    await ctx.send("Halika!!! De fáj Trianon")
    

@bot.command(name="play")
async def play(ctx, *, query: str):
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
@bot.command(name="stop")
async def stop(ctx):
    if ctx.voice_client is not None and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Leállítva a lejátszást.")
    else:
        await ctx.send("Nincs lejátszás folyamatban.")
@bot.command(name="pause")
async def pause(ctx):
    if ctx.voice_client is not None and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("Szüneteltetve a lejátszást.")
    else:
        await ctx.send("Nincs lejátszás folyamatban.")
@bot.command(name="resume")
async def resume(ctx):
    if ctx.voice_client is not None and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("Folytatva a lejátszást.")
    else:
        await ctx.send("Nincs szüneteltetett lejátszás.")
@bot.command(name="set-volume")
async def set_volume(ctx, volume: float):
    if ctx.voice_client is not None and ctx.voice_client.is_playing():
        ctx.voice_client.source.volume = max(0.0, min(volume, 1.0))
        await ctx.send(f"Hangerő beállítva: {ctx.voice_client.source.volume:.1f}")
    else:
        await ctx.send("Nincs lejátszás folyamatban.")
@bot.command(name="leave")
async def leave(ctx):
    if ctx.voice_client is not None:
        await ctx.voice_client.disconnect()
    else:
        await ctx.send("Nem vagyok hangcsatornán.")
@bot.command(name="p")
async def p(ctx, *, query: str):
    return await play(ctx, query=query)
@bot.command(name="download")
async def download(ctx, *, query: str):
    query = query.split(" ")
    url = query[0]
    alias = query[1]
    
    os.system(f"yt-dlp -x --audio-format mp3 {url} -o music/{alias}.mp3")
    playlist[alias] = alias
    with open("songs.json", "w") as f:
        json.dump(playlist, f, indent=4)
    await ctx.send(f"Letöltve: **{alias}**")
@bot.command(name="roll_dice")
async def roll_dice(ctx,*,query: str):
    #pl: 1d20, 2d4, 3d6 +5
    if "+" in query:
        parts = query.strip().lower().split("+")
        result = 0
        for part in parts:
            num, die = map(int, part.lower().split("d"))
            result += sum(random.randint(1, die) for _ in range(num))
    else:
        num, die = map(int, query.lower().split("d"))
        result = sum(random.randint(1, die) for _ in range(num))
    await ctx.send(f"🎲 Dobás eredménye: **{result}**")
@bot.command(name="takarodj")
async def takarodj(ctx):
    await leave(ctx)
bot.run(os.getenv('DISCORD_TOKEN'))

