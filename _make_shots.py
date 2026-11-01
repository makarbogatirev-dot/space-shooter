"""Headless render of real game frames -> PNG screenshots for the site."""
import os
import random
import sys

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame

BASE = os.path.dirname(os.path.abspath(__file__))
GAME_DIR = os.path.join(BASE, "space_shuter v1.0")
IMG_DIR = os.path.join(GAME_DIR, "images")
OUT_DIR = os.path.join(BASE, "site", "assets", "screenshots")
os.makedirs(OUT_DIR, exist_ok=True)

pygame.init()
pygame.font.init()

WIDTH, HEIGHT = 600, 800
screen = pygame.display.set_mode((WIDTH, HEIGHT))

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

font_name = pygame.font.match_font("arial")


def draw_text(surf, text, size_text, x, y):
    font = pygame.font.Font(font_name, size_text)
    text_surface = font.render(text, True, WHITE)
    text_rect = text_surface.get_rect()
    text_rect.midtop = (x, y)
    surf.blit(text_surface, text_rect)


bg = pygame.image.load(os.path.join(IMG_DIR, "blue.png")).convert()
bg = pygame.transform.scale(bg, (WIDTH, HEIGHT))
bg_rect = bg.get_rect()

player_img = pygame.image.load(os.path.join(IMG_DIR, "player.png")).convert()
player_img.set_colorkey(BLACK)

laser_img = pygame.image.load(os.path.join(IMG_DIR, "Laser", "laserRed07.png")).convert()

meteors = []
for i in range(1, 20):
    img = pygame.image.load(os.path.join(IMG_DIR, "Meteors", f"{i}.png")).convert()
    meteors.append(img)


def make_meteor(idx, x, y, angle=0):
    img = meteors[idx % len(meteors)].copy()
    img.set_colorkey(BLACK)
    if angle:
        img = pygame.transform.rotate(img, angle)
    rect = img.get_rect(center=(x, y))
    return img, rect


def render_frame(score, player_x, player_y, meteor_specs, lasers, flashes=()):
    screen.fill(BLACK)
    screen.blit(bg, bg_rect)
    for img, rect in flashes:
        screen.blit(img, rect)
    for img, rect in meteor_specs:
        screen.blit(img, rect)
    for rect in lasers:
        screen.blit(laser_img, rect)
    screen.blit(player_img, player_img.get_rect(center=(player_x, player_y)))
    draw_text(screen, f"Score:{score}", 45, 75, 15)


random.seed(7)

# --- Shot 1: classic gameplay, ship at bottom, scattered meteors, one laser ---
met = []
positions = [(120, 140, 25), (330, 90, -40), (480, 220, 60), (90, 380, 15),
             (520, 430, -25), (260, 300, 80), (400, 560, -60), (150, 600, 30)]
for i, (x, y, a) in enumerate(positions):
    met.append(make_meteor(i * 2, x, y, a))
lasers = [laser_img.get_rect(center=(300, 520)), laser_img.get_rect(center=(300, 330)),
          laser_img.get_rect(center=(300, 150))]
render_frame(27, 300, HEIGHT - 45, met, lasers)
pygame.image.save(screen, os.path.join(OUT_DIR, "gameplay1.png"))

# --- Shot 2: dense meteor field ---
met = []
for i in range(12):
    x = random.randint(60, WIDTH - 60)
    y = random.randint(60, HEIGHT - 250)
    met.append(make_meteor(random.randrange(19), x, y, random.randrange(360)))
lasers = [laser_img.get_rect(center=(200, 480)), laser_img.get_rect(center=(430, 400))]
render_frame(134, 200, HEIGHT - 45, met, lasers)
pygame.image.save(screen, os.path.join(OUT_DIR, "gameplay2.png"))

# --- Shot 3: near miss / dodge ---
met = [make_meteor(3, 355, 610, 15), make_meteor(9, 210, 520, -35),
       make_meteor(14, 470, 480, 50), make_meteor(6, 320, 200, 90),
       make_meteor(11, 120, 300, -70)]
lasers = [laser_img.get_rect(center=(355, 470))]
render_frame(8, 300, HEIGHT - 45, met, lasers)
pygame.image.save(screen, os.path.join(OUT_DIR, "gameplay3.png"))

# --- Shot 4: hero wide shot (two frames side by side, 1200x800) ---
canvas = pygame.Surface((WIDTH * 2, HEIGHT))
canvas.fill(BLACK)
render_frame(52, 180, HEIGHT - 45,
             [make_meteor(1, 250, 250, 20), make_meteor(8, 420, 150, -50),
              make_meteor(16, 300, 450, 70), make_meteor(5, 100, 550, -15)],
             [laser_img.get_rect(center=(180, 500)), laser_img.get_rect(center=(180, 300))])
canvas.blit(screen, (0, 0))
render_frame(53, 430, HEIGHT - 45,
             [make_meteor(4, 150, 200, 45), make_meteor(12, 350, 350, -80),
              make_meteor(18, 500, 500, 30), make_meteor(7, 250, 600, 110)],
             [laser_img.get_rect(center=(430, 420)), laser_img.get_rect(center=(430, 240))])
canvas.blit(screen, (WIDTH, 0))
pygame.image.save(canvas, os.path.join(OUT_DIR, "hero.png"))

pygame.quit()
print("OK:", sorted(os.listdir(OUT_DIR)))
