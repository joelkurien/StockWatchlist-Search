from django.shortcuts import render
from django.http import HttpResponse
from django.core.exceptions import ValidationError
from rest_framework.decorators import api_view
from rest_framework.response import Response
import requests
import asyncio
import finnhub
import pandas
import datetime
from .feateng import FeatureAnalysis
from dotenv import load_dotenv
import os


from .forms import StockSearchForm
from . import models

load_dotenv("./content.env")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")

__finnhubClient = finnhub.Client(api_key=FINNHUB_API_KEY)
__featureAnalysis = FeatureAnalysis()

# Create your views here.
def index(request):
    user = models.UserLogin(userName='Joel', userPassword="Jello123!@##@!", dateOfBirth=datetime.date(2001,5,12)) 
    user.save()   
    return HttpResponse("Hello, world. This is the base.")

@api_view(['POST'])
def searchStock(request):
    try:
        stockName = request.data.get("stock")
        closedPrices = getStockClosePrice(stockName)
        print(closedPrices)
        return Response(closedPrices)
    except Exception as err:
        return Response("Failure in sending data")

def getStockClosePrice(stock, time):
    timeOptions = {
        'intraday': f'https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={stock}&interval=5min&apikey={ALPHAVANTAGE_API_KEY}',
        'daily': f'https://www.alphavantage.co/query?function=TIME_SERIES_DAILY_ADJUSTED&symbol={stock}&apikey={ALPHAVANTAGE_API_KEY}',
        'weekly': f'https://www.alphavantage.co/query?function=TIME_SERIES_WEEKLY_ADJUSTED&symbol={stock}&apikey={ALPHAVANTAGE_API_KEY}',
        'monthly': f'https://www.alphavantage.co/query?function=TIME_SERIES_MONTHLY_ADJUSTED&symbol={stock}&apikey={ALPHAVANTAGE_API_KEY}'
    }
    try:
        if time in timeOptions:
            url = timeOptions[time]
        r = requests.get(url)
        data = r.json()
        timeSeries = list(data.keys())[1]
        
        priceData = {}
        for time in data[timeSeries]:
            entry = data[timeSeries][time]
            close_key = next((k for k in entry if "close" in k.lower()), None)
            volume_key = next((k for k in entry if "volume" in k.lower()), None)
            priceData[time] = {
                'close': close_key,
                'volume': volume_key
            }
        print(priceData)
        return priceData

    except Exception as err:
        return Response("Error in generating data")

@api_view(['POST'])    
def getBasicFinancialMetrics(request):
    try:
        stock = request.data.get("stock")
        metricData = __finnhubClient.company_basic_financials(stock, 'all')
        baseStatJson = {}
        flag = False
        if metricData and metricData['symbol'] == stock:
            basicMetrics = metricData['metric']  
            metricJson = {
                "10DayAvgTradeVol": [
                    "10 Day Average Trading Volume", 
                    basicMetrics['10DayAverageTradingVolume'] if basicMetrics and basicMetrics['10DayAverageTradingVolume'] != None else 0
                ],
                "52WeekHigh": [
                    "Annual Highest Price",
                    basicMetrics["52WeekHigh"] if basicMetrics and basicMetrics['52WeekHigh'] != None else 0,
                ],
                "52WeekLow": [
                    "Annual Lowest Price",
                    basicMetrics["52WeekLow"] if basicMetrics and basicMetrics['52WeekLow'] != None else 0,
                ],
                "52WeekReturn": [
                    "Annual Return",
                    basicMetrics["52WeekPriceReturnDaily"] if basicMetrics and basicMetrics['52WeekPriceReturnDaily'] != None else 0,
                ],
                "beta": [
                    "Beta(1Y)",
                    basicMetrics["beta"] if basicMetrics and basicMetrics['beta'] != None else 0
                ]
            }
            baseStatJson = metricJson
            flag = True
        
        dailyStockUrl = f'https://www.alphavantage.co/query?function=TIME_SERIES_DAILY_ADJUSTED&symbol={stock}&apikey={ALPHAVANTAGE_API_KEY}'
        r = requests.get(dailyStockUrl)
        data = r.json()
        timeSeries = list(data.keys())[1]
        monthAvgVol = __featureAnalysis.calculateAverageFromJson(data[timeSeries], 'monthly_average')
        dailyAvgVol = __featureAnalysis.calculateAverageFromJson(data[timeSeries], 'daily_average')
        baseStatJson['avgDailyVol'] = [
            "Volume",
            dailyAvgVol[[idx for idx in dailyAvgVol.index if 'volume' in idx][0]]
        ]
        baseStatJson['avgVol30d'] = [
            "Average Volume(30D)",
            monthAvgVol[[idx for idx in monthAvgVol.index if 'volume' in idx][0]]
        ]
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=30)
        earnings = __finnhubClient.earnings_calendar(_from=yesterday.strftime('%Y-%m-%d'), to=today.strftime('%Y-%m-%d'), symbol=stock, international=False)['earningsCalendar']
        if earnings and 'epsActual' in earnings[0]:
            baseStatJson['baseEPS'] = [
                "Basic EPS",
                earnings[0]['epsActual']
            ]

        baseStatJson['marketCap'] = [
            "Market Capitalization",
            __finnhubClient.company_profile2(symbol=stock).get("marketCapitalization")
        ]
        if not flag:
            raise ValidationError("The stock has no valid metric values/stock data is incorrect")
        return Response(baseStatJson)
    except finnhub.FinnhubAPIException as ferr:
        return Response({})
    except (Exception) as err:
        return Response(err)    
    
