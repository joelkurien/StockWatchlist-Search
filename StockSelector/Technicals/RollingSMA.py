from collections import deque

class RollingSMA():
    def __init__(self, window):
        self.queue = deque()
        if window > 0:
            self.queue = deque(maxlen=window)
        self.window = window
        self.s = 0
    
    def seed(self, closePrice):
        for price in closePrice[-self.window:][::-1]:
            self.accumulate(price)
        
    def accumulate(self, price):
        if len(self.queue) == self.queue.maxlen:
            self.s -= self.queue.popleft()
        self.queue.append(price)
        self.s += price
        return self.sma()
    
    def sma(self):
        return (self.s / len(self.queue)) if self.queue else None