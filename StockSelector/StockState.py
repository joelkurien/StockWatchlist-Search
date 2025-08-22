from channels.generic.websocket import AsyncWebsocketConsumer
import json
import asyncio
import websockets
import redis
import aiohttp
import finnhub
import datetime
from dotenv import load_dotenv
import os

load_dotenv('../content.env')
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

class StockState(AsyncWebsocketConsumer):
    async def connect(self):
        print(ALPHAVANTAGE_API_KEY)
        self.stockTick = self.scope['url_route']['kwargs'].get('stockTick')
        self.stockEPS = None
        await self.accept() #start connection to your websocket
        try:
            #setup a connection to the finnhub websocket
            self.finnhubSocket = await websockets.connect(
                f"wss://ws.finnhub.io?token={FINNHUB_API_KEY}"
            )
            self.finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)

            today = datetime.date.today()
            yesterday = today - datetime.timedelta(days=30)
        except Exception as e:
            print(e)
        try:
            #send a subscription message to the finnhub socket to get the data of a stock
            await self.finnhubSocket.send(json.dumps({
                "type": "subscribe",
                "symbol": self.stockTick
            }))
        except Exception as e:
            print(e) 
        self.keep_streaming = True #continue streaming of the redis cache
        self.stream_task = asyncio.create_task(self.priceStream()) #create a stream task to run the stream prices fn on every connection
        
    #disconnect from the websocket
    async def disconnect(self, close_code):
        self.keep_streaming = False
        if hasattr(self, 'stream_task'):
            try:
                self.stream_task.cancel()
            except Exception as err:
                print(err)
        
        try:
            if hasattr(self, "finnhubSocket"):
                await self.finnhubSocket.send(json.dumps({
                    "type": "unsubscribe",
                    "symbol": self.stockTick
                }))
                await self.finnhubSocket.close()
        except Exception as e:
            print(e)
    
    async def receive(self, text_data = None, bytes_data = None):
        if text_data:
            data = json.loads(text_data)
            action = data.get("action")
            if action == "get_price":
                livePriceData = await self.getCachedPrice()
                if livePriceData is not None:
                    pchange = (livePriceData['price'] - self.finnhub_client.quote(self.stockTick).get('pc')) / self.finnhub_client.quote(self.stockTick).get('pc') * 100
                    await self.send(json.dumps({
                        "symbol": self.stockTick,
                        "price": livePriceData['price'],
                        "pchange": pchange,
                        "sign": '+' if pchange >= 0 else '-',
                        "delta": livePriceData['price'] - self.finnhub_client.quote(self.stockTick).get('pc')
                    }))
                
    async def getCachedPrice(self):
        cacheKey  = f"stock_{self.stockTick}"
        cacheResponse = redis_client.get(cacheKey)
        currentPrice = None
        if cacheResponse is None:
            currentPrice = cacheResponse
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://finnhub.io/api/v1/quote",
                    params={'symbol': self.stockTick, 'token': FINNHUB_API_KEY}
                ) as response:
                    resp = await response.json()
                    
                    currentPrice = resp.get("c") 
                    pchange = 0 if currentPrice is None else (currentPrice - self.finnhub_client.quote(self.stockTick).get('pc')) / self.finnhub_client.quote(self.stockTick).get('pc') * 100
                    sign = '+' if pchange >= 0 else '-'
                    livePriceState = {
                        'price': currentPrice,
                        'pchange': pchange,
                        'sign': sign,
                        "delta": currentPrice - self.finnhub_client.quote(self.stockTick).get('pc')
                    }
                    if livePriceState is not None:
                        redis_client.setex(cacheKey, 60, json.dumps(livePriceState))
        else:
            livePriceState = json.loads(cacheResponse)
        return livePriceState
    
    #function to receive data from the finnhub websocket
    async def priceStream(self):
        try:
            while self.keep_streaming:
                try:
                    message = await asyncio.wait_for(self.finnhubSocket.recv(), timeout = 15) #waits for a response from the finnhub socket every 5s
                    data = json.loads(message)
                    price = None
                    if data.get("type") == "trade":
                        tradePrice = data['data'][0].get('p')
                        if tradePrice is not None:
                            cacheKey = f'stock_{self.stockTick}'
                            price = tradePrice
                    elif data.get("type") == "ping":
                        livePriceData = await self.getCachedPrice()
                        if livePriceData is not None:
                            price = livePriceData['price']
                    
                    openingPrice = self.finnhub_client.quote(self.stockTick).get('pc')
                    pchange = (price - openingPrice)/openingPrice * 100
                    liveData = {
                        'price': price, 
                        'pchange': pchange,
                        'sign': '+' if pchange is not None and pchange >=0 else '-',
                        "delta": price - openingPrice
                    }
                    if data.get("type") == 'trade':
                        redis_client.setex(cacheKey, 60, json.dumps(liveData))
                    await self.send(json.dumps(liveData))
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    print("Finnhub connection as been closed")
                    await asyncio.sleep(2)
                except Exception as err:
                    print(err)
                    print("Unexpected error")
                    await asyncio.sleep(1)
        except Exception as e:
            print("Error price streaming: ", e) 