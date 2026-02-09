import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

async def get_spotify_token():
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")

    if not client_id or not client_secret:
        return None

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                auth=aiohttp.BasicAuth(client_id, client_secret)
            ) as res:
                if res.status != 200:
                    return None
                data = await res.json()
                return data.get("access_token")
        except Exception as e:
            print(f"Error getting Spotify token: {e}")
            return None

async def get_spotify_track_query(spotify_url):
    token = await get_spotify_token()
    if not token:
        return None, "❌ Spotify authentication failed."

    try:
        track_id = spotify_url.split("track/")[1].split("?")[0]
    except IndexError:
        return None, "❌ Invalid Spotify track URL."

    url = f"https://api.spotify.com/v1/tracks/{track_id}"
    headers = {"Authorization": f"Bearer {token}"}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as res:
                if res.status != 200:
                    return None, f"❌ Spotify track not found (HTTP {res.status})"
                data = await res.json()
                title = data["name"]
                artist = data["artists"][0]["name"]
                return f"{title} {artist}", None
        except Exception as e:
            return None, f"❌ Spotify error: {e}"
