class ExpontialMovingAverage():
    def __init__(self, period, smoothing):
        self.period = period
        self.ema = 0
        self.alpha = 0
        if self.period > 0:
            self.alpha = (smoothing / (1+self.period))
        
    def seed(self, price):
        self.ema = price
    
    def update(self, price):
        self.ema = price if self.ema is None or self.ema == 0 else (price * self.alpha) + (self.ema * (1-self.alpha))
        return self.ema