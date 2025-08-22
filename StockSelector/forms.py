from django import forms 

class StockSearchForm(forms.Form):
    stockName = forms.CharField(label = "Stock", max_length=255)