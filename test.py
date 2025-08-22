import kagglehub

print('hello')
# Download latest version
path = kagglehub.dataset_download("finnhub/reported-financials")

print("Path to dataset files:", path)