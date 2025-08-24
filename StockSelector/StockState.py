import contextlib
from channels.generic.websocket import AsyncWebsocketConsumer
import os, json, asyncio, aiohttp, datetime
import websockets
import finnhub
import orjson
from redis import asyncio as aioredis
from dotenv import load_dotenv
from StockSelector.Technicals.RollingSMA import RollingSMA
from StockSelector.Technicals.StreamingEMA import StreamingEMA

load_dotenv('./content.env')
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")

class StockState(AsyncWebsocketConsumer):
    async def connect(self):
        self.stockTick = self.scope['url_route']['kwargs'].get('stockTick')
        if not FINNHUB_API_KEY:
            await self.close(code=4001)
            return None
        self.redis = aioredis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        self.p_latest = f"stock|{self.stockTick}|latest"
        self.p_open = f"stock|{self.stockTick}|open|{datetime.date.today():%Y-%m-%d}"
        self.p_bars = f"stock|{self.stockTick}|bars|5m"
        self.p_ind = f"stock|{self.stockTick}|indicators|5m"
        
        self.ind_periods = {
            "sma": 20,
            "ema": 20,
            "rsi": 14,
            "macd": 12
        }
        self.sma = RollingSMA(self.ind_periods['sma'])
        self.ema = StreamingEMA(self.ind_periods['ema'], 2)
        
        self.currentBucketStart = None
        self.currentBucketClose = None
        
        await self.accept()
        
        self.openingPrice = await self._getOpeningPrice()
        
        await self._getRedisSeed()
        
        self.keep_streaming = True
        self.stream_task = asyncio.create_task(self.priceStream())
        
    async def disconnect(self, close_code):
        self.keep_streaming = False
        if hasattr(self, 'stream_task'):
            try:
                self.stream_task.cancel()
                with contextlib.suppress(Exception):
                    await self.stream_task
            except Exception as err:
                print("Error cancelling stream task:", err)
        
        if hasattr(self, 'finnhubSocket'):
            try:
                with contextlib.suppress(Exception):
                    await self._ws_unsubscribe(self.stockTick)
                    await self.finnhubSocket.close()
            except Exception as e:
                print("Error closing websocket:", e)
        
        with contextlib.suppress(Exception):
            close = getattr(self.redis, "aclose", None)
            if callable(close):
                await close()
            else:
                self.redis.close()
                connPool = getattr(self.redis, "connection_pool", None)
                if connPool and hasattr(connPool, "disconnect"):
                    connPool.disconnect()
                   
    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except Exception as e:
            return
        if data.get("action") == "get_price":
            liveData = await self.redis.get(self.p_latest)
            if liveData:
                await self.send(liveData)
    
    async def _getOpeningPrice(self):
        cacheData = await self.redis.get(self.p_open)
        if cacheData is not None and float(cacheData) > float(0):
            try:
                return float(cacheData)
            except Exception as e:
                pass
        
        url = f'https://finnhub.io/api/v1/quote?symbol={self.stockTick}&token={FINNHUB_API_KEY}'
        params = {'symbol': self.stockTick, 'token': FINNHUB_API_KEY}
        timeout = aiohttp.ClientTimeout()
        opening = 0
        try:
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        opening = data.get('pc', 0) or data.get('o', 0)
        except (Exception, 
                finnhub.FinnhubAPIException,
                finnhub.FinnhubRequestException):
            opening = 0
        
        try:
            openingF = float(opening)
        except Exception as e:
            openingF = 0
        await self.redis.setex(self.p_open, 24 * 60 * 60, openingF)
        return openingF
    
    async def _getRedisSeed(self):
        count = max(self.ind_periods['sma'], self.ind_periods['ema']) + 10
        candles = await self.redis.lrange(self.p_bars, 0, count)
        priceQueue = []
        for candle in candles:
            try:
                cObj = json.loads(candle)
                priceQueue.append(cObj['close'])
            except Exception as e:
                continue
        
        if priceQueue:
            self.sma.seed(priceQueue)
            self.ema.seed(priceQueue[-1])
        
    async def _ws_unsubscribe(self, symbol):
        await self.finnhubSocket.send(json.dumps({
            "type": "unsubscribe",
            "symbol": symbol
        }))
    
    async def _ws_subscribe(self, symbol):
        await self.finnhubSocket.send(json.dumps({
            "type": "subscribe",
            "symbol": symbol
        }))
    
    @staticmethod
    def _startBucket(time):
        s = time // 1000
        return s // 300 * 300
    
    async def _closeBucket(self):
        if self.currentBucketStart is None or self.currentBucketClose is None:
            return 
        candle = {'ts': int(self.currentBucketStart), 'close': float(self.currentBucketClose)}
        
        async with self.redis.pipeline() as pipe:
            await pipe.lpush(self.p_bars, orjson.dumps(candle).decode())
            await pipe.ltrim(self.p_bars, 0, 499)
            await pipe.execute()
        
        smaValue = self.sma.accumulate(candle['close'])
        emaValue = self.ema.update(candle['close'])
        
        await self.redis.set(
            self.p_ind, 
            orjson.dumps({
                "ts": candle['ts'],
                f"sma{self.ind_periods['sma']}": smaValue,
                f"ema{self.ind_periods['ema']}": emaValue
            }).decode(),
        )

    async def _livePublish(self, price):
        op = self.openingPrice or 0
        if op:
            pchange = (price - op) / op * 100
            delta = price - op
        else:
            pchange = 0
            delta = 0
        
        live = {
            "symbol": self.stockTick,
            "price": float(price),
            "pchange": float(pchange),
            "sign": "+" if pchange >= 0 else "-",
            "delta": float(delta),
        }

        payload = orjson.dumps(live).decode()
        await self.redis.setex(self.p_latest, 60, payload)
        await self.send(payload)
    
    async def priceStream(self):
        backoff = 1
        maxBackoff = 30
        while self.keep_streaming:
            try:
                async with websockets.connect(
                    f"wss://ws.finnhub.io?token={FINNHUB_API_KEY}"
                ) as ws:
                    self.finnhubSocket = ws
                    await self._ws_subscribe(self.stockTick)
                    backoff = 1
                    async for msg in ws:
                        try:
                            data = orjson.loads(msg)
                        except Exception:
                            continue
                        
                        callType = data.get("type")
                        if callType == "trade":
                            for tr in data.get("data", []):
                                if tr.get("s") != self.stockTick:
                                    continue
                                try:
                                    price = float(tr.get("p"))
                                    time = int(tr.get("t"))
                                except Exception:
                                    continue
                                bucket = self._startBucket(time)
                                if self.currentBucketStart is None or self.currentBucketStart != bucket:
                                    self.currentBucketStart = bucket
                                
                                if bucket != self.currentBucketStart:
                                    await self._closeBucket()
                                    self.currentBucketStart = bucket
                                    self.currentBucketClose = None
                                
                                self.currentBucketClose = price
                                await self._livePublish(price)
                        elif callType == "ping":
                            pass
            except asyncio.CancelledError:
                break
            except (websockets.exceptions.ConnectionClosed,
                    websockets.exceptions.ConnectionClosedError,
                    websockets.exceptions.ConnectionClosedOK):
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, maxBackoff)
            except Exception as e:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, maxBackoff)
