import time
import aigpy
from bot import LOGGER
from bot.helpers.translations import lang
from bot.helpers.database.postgres_impl import set_db
from bot.helpers.buttons.settings_buttons import common_auth_set

import bot.helpers.tidal_func.apikey as apiKey

from bot.helpers.tidal_func.tidal import *
from bot.helpers.tidal_func.enums import *
from bot.helpers.tidal_func.download import *
from bot.helpers.tidal_func.settings import TIDAL_TOKEN

def __displayTime__(seconds, granularity=2):
    if seconds <= 0:
        return "unknown"

    result = []
    intervals = (
        ('weeks', 604800),
        ('days', 86400),
        ('hours', 3600),
        ('minutes', 60),
        ('seconds', 1),
    )

    for name, count in intervals:
        value = seconds // count
        if value:
            seconds -= value * count
            if value == 1:
                name = name.rstrip('s')
            result.append("{} {}".format(value, name))
    return ', '.join(result[:granularity])

async def loginByWeb(bot, msg, c_id):
    try:
        url = TIDAL_API.getDeviceCode()
        await bot.edit_message_text(
            chat_id=c_id,
            message_id=msg.message.id, 
            text=lang.select.TIDAL_AUTH_NEXT_STEP.format(
                url,
                __displayTime__(TIDAL_API.key.authCheckTimeout)
            ),
            disable_web_page_preview=True
        )
        start = time.time()
        elapsed = 0
        while elapsed < TIDAL_API.key.authCheckTimeout:
            elapsed = time.time() - start
            if not TIDAL_API.checkAuthStatus():
                time.sleep(TIDAL_API.key.authCheckInterval + 1)
                continue

            await bot.edit_message_text(
                chat_id=c_id,
                message_id=msg.message.id, 
                text=lang.select.TIDAL_AUTH_SUCCESS.format(
                    __displayTime__(int(TIDAL_API.key.expiresIn))),
                disable_web_page_preview=True,
                reply_markup=common_auth_set("tidal")
            )

            TIDAL_TOKEN.userid = TIDAL_API.key.userId
            TIDAL_TOKEN.countryCode = TIDAL_API.key.countryCode
            TIDAL_TOKEN.accessToken = TIDAL_API.key.accessToken
            TIDAL_TOKEN.refreshToken = TIDAL_API.key.refreshToken
            TIDAL_TOKEN.expiresAfter = time.time() + int(TIDAL_API.key.expiresIn)
            TIDAL_TOKEN.save()
            return True, None

        raise Exception("Login Operation timed out.")
    except Exception as e:
        return False, e

def loginByConfig():
    try:
        if aigpy.string.isNull(TIDAL_TOKEN.accessToken):
            return False, None
        # If token is valid, return True
        if TIDAL_API.verifyAccessToken(TIDAL_TOKEN.accessToken):
            msg = lang.select.TIDAL_ALREADY_AUTH.format(
                __displayTime__(int(TIDAL_TOKEN.expiresAfter - time.time())))

            TIDAL_API.key.countryCode = TIDAL_TOKEN.countryCode
            TIDAL_API.key.userId = TIDAL_TOKEN.userid
            TIDAL_API.key.accessToken = TIDAL_TOKEN.accessToken
            return True, msg
        # If token is not valid but refresh token is, refresh token and return True
        if TIDAL_API.refreshAccessToken(TIDAL_TOKEN.refreshToken):
            msg = lang.select.TIDAL_ALREADY_AUTH.format(
                __displayTime__(int(TIDAL_API.key.expiresIn)))

            TIDAL_TOKEN.userid = TIDAL_API.key.userId
            TIDAL_TOKEN.countryCode = TIDAL_API.key.countryCode
            TIDAL_TOKEN.accessToken = TIDAL_API.key.accessToken
            TIDAL_TOKEN.expiresAfter = time.time() + int(TIDAL_API.key.expiresIn)
            TIDAL_TOKEN.save()
            return True, msg
        else:
            TokenSettings().save()
            return False, None
    except Exception as e:
        return False, None

async def checkLoginTidal():
    db_auth, _ = set_db.get_variable("TIDAL_AUTH_DONE")
    if not db_auth:
        return False, lang.select.TIDAL_NOT_AUTH
    auth, msg = loginByConfig()
    if auth:
        return True, msg
    else:
        return False, lang.select.TIDAL_NOT_AUTH

async def loginTidal(bot, msg, c_id):
    await loginByWeb(bot, msg, c_id)

'''
=================================
START DOWNLOAD
=================================
'''
async def startTidal(string, bot, c_id, r_id, u_id, u_name):
    strings = string.split(" ")
    for item in strings:
        if aigpy.string.isNull(item):
            continue
        try:
            etype, obj = TIDAL_API.getByString(item)
        except Exception as e:
            LOGGER.warning(str(e) + " [" + item + "]")
            return

        try:
            await start_type(etype, obj, bot, c_id, r_id, u_id, u_name)
        except Exception as e:
            LOGGER.warning(str(e))

async def start_type(etype: Type, obj, bot, c_id, r_id, u_id, u_name):
    if etype == Type.Album:
        await start_album(obj, bot, c_id, r_id, u_id, u_name)
    elif etype == Type.Track:
        await start_track(obj, bot, c_id, r_id, u_id, u_name)
    elif etype == Type.Artist:
        await start_artist(obj, bot, c_id, r_id, u_id, u_name)
    elif etype == Type.Playlist:
        await start_playlist(obj, bot, c_id, r_id, u_id, u_name)
    elif etype == Type.Mix:
        await start_mix(obj, bot, c_id, r_id, u_id, u_name)

async def start_mix(obj: Mix, bot, c_id, r_id, u_id, u_name):
    for index, item in enumerate(obj.tracks):
        album = TIDAL_API.getAlbum(item.album.id)
        item.trackNumberOnPlaylist = index + 1
        await postCover(album, bot, c_id, r_id, u_name)
        await downloadTrack(item, album, bot=bot, c_id=c_id, r_id=r_id, u_id=u_id)

async def start_playlist(obj: Playlist, bot, c_id, r_id, u_id, u_name):
    #TODO FIX COVER
    tracks, videos = TIDAL_API.getItems(obj.uuid, Type.Playlist)
    for index, item in enumerate(tracks):
        album = TIDAL_API.getAlbum(item.album.id)
        item.trackNumberOnPlaylist = index + 1
        #await postCover(album, bot, c_id, r_id)
        await downloadTrack(item, album, obj, bot=bot, c_id=c_id, r_id=r_id, u_id=u_id)

async def start_artist(obj: Artist, bot, c_id, r_id, u_id, u_name):
    albums = TIDAL_API.getArtistAlbums(obj.id, TIDAL_SETTINGS.includeEP)
    for item in albums:
        await start_album(item, bot, c_id, r_id, u_id, u_name)

async def start_track(obj: Track, bot, c_id, r_id, u_id, u_name):
    album = TIDAL_API.getAlbum(obj.album.id)
    await downloadTrack(obj, album, bot=bot, c_id=c_id, r_id=r_id, u_id=u_id, u_name=u_name)

async def start_album(obj: Album, bot, c_id, r_id, u_id, u_name):
    tracks, videos = TIDAL_API.getItems(obj.id, Type.Album)
    await postCover(obj, bot, c_id, r_id, u_name)
    await downloadTracks(tracks, obj, None, bot, c_id, r_id, u_id)


'''
=================================
TIDAL API CHECKS
=================================
'''

async def checkAPITidal():
    if not apiKey.isItemValid(TIDAL_SETTINGS.apiKeyIndex):
        LOGGER.warning(lang.select.ERR_API_KEY)
    else:
        index = TIDAL_SETTINGS.apiKeyIndex
        TIDAL_API.apiKey = apiKey.getItem(index)

async def getapiInfoTidal():
    i = 0
    platform = []
    validity = []
    quality = []
    index = []
    list = apiKey.__API_KEYS__
    for item in list['keys']:
        index.append(i)
        platform.append(item['platform'])
        validity.append(item['valid'])
        quality.append(item['formats'])
        i += 1
    return index, platform, validity, quality
