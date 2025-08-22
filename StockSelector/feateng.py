import numpy as np
import pandas as pd

class FeatureAnalysis():
    def calculateAverageFromJson(self, jsonObject, time):
        df = pd.DataFrame.from_dict(jsonObject, orient='index')
        columns = df.columns
        for col in columns:
            df = df.astype({col: float})
        end_date = pd.to_datetime(df.index.max())
        avg_df = None
        if time == 'monthly_average':
            start_date = end_date - pd.Timedelta(days=30)
            last_month = df[(pd.to_datetime(df.index) >= start_date) & (pd.to_datetime(df.index) <=end_date)]
            avg_df = last_month.mean()
        elif time == 'daily_average':
            start_date = end_date - pd.Timedelta(hours=24)
            last_day = df[(pd.to_datetime(df.index) >= start_date) & (pd.to_datetime(df.index) <=end_date)]
            avg_df = last_day.mean()
        if avg_df is not None and not avg_df.empty:
            return avg_df
        raise ValueError("Invalid Average Dataframe")