"""Fictional logistic growth model; no external inputs."""
import math

def height(day, rate=0.18):
    return 30 / (1 + math.exp(-rate * (day - 10)))

if __name__ == "__main__":
    for day in range(21):
        print(day, round(height(day), 3))
