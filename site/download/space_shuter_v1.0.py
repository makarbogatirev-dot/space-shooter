import pygame
import random
import sys
from os import path

def resource_path(rel):
    """Path to a resource: works both from script and from a PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", path.dirname(__file__))
    return path.join(base, rel)

font_name = pygame.font.match_font('kalibri')

def draw_text(surf,text,size_text,x,y):
    font = pygame.font.Font(font_name, size_text)
    text_surface = font.render(text, True, WHITE)
    text_rect = text_surface.get_rect()
    text_rect.midtop = (x, y)
    surf.blit(text_surface, text_rect)

def CheatsON():
    global God
    God = True
def CheatsOFF():
    global God
    God = False

class Player(pygame.sprite.Sprite):
    def __init__(self):
        pygame.sprite.Sprite.__init__(self)
        self.image = player_img
        self.image.set_colorkey(BLACK)
        self.rect = self.image.get_rect()
        self.rect.centerx = WIDTH / 2
        self.rect.centery = HEIGHT - 45
        self.speedx = 0
        self.shoot_delay = 100
        self.last_shoot = pygame.time.get_ticks()
        self.radius = self.rect.width * 0.25
        #pygame.draw.circle(self.image, RED,self.rect.center, self.radius)
    def update(self):
        if self.rect.right <= 0:
            self.rect.left = WIDTH
        elif self.rect.left >= WIDTH:
            self.rect.right = 0
        self.speedx = 0
        keystate = pygame.key.get_pressed()
        if keystate[pygame.K_LEFT] or keystate[pygame.K_a]:
            self.speedx = -10
        if keystate[pygame.K_RIGHT] or keystate[pygame.K_d]:
            self.speedx = 10
        if keystate[pygame.K_SPACE]:
            self.create_bullet()
        if keystate[pygame.K_9]:
            if God == False:
                print("Cheats: ON")
            CheatsON()
        if keystate[pygame.K_0]:
            if God == True:
                print("Cheats: OFF")
            CheatsOFF()
        self.rect.x += self.speedx
    def create_bullet(self):
        laser_img = pygame.image.load(resource_path(path.join("images","laser/laserRed07.png"))).convert()
        now = pygame.time.get_ticks()
        if now - self.last_shoot >= self.shoot_delay:
            bullet = Bullets()
            bullet.image = laser_img
            bullets.add(bullet)
            sprites.add(bullet)
            self.last_shoot = now

class Mobs(pygame.sprite.Sprite):
    def __init__(self):
        pygame.sprite.Sprite.__init__(self)
        self.image_orig = random.choice(meteors_img)
        self.image_orig.set_colorkey(BLACK)
        self.image = self.image_orig.copy()
        self.rotation = 0
        self.rotation_speed = random.randrange(-5, 5)
        self.rotation_last_update = pygame.time.get_ticks()
        self.rect = self.image.get_rect()
        self.rect.centerx = random.randrange(WIDTH - self.rect.width)
        self.rect.centery = -100
        self.speedx = random.randrange(-5, 5)
        self.speedy = random.randrange(1, 15)
        self.radius = self.rect.width * 0.75
        #pygame.draw.circle(self.image, RED,self.rect.center, self.radius)
    def update(self):
        self.rect.y += self.speedy
        self.rect.x += self.speedx
        if self.rect.y >= HEIGHT:
            self.rect.x = random.randrange(WIDTH - self.rect.width)
            self.rect.y = -100
            self.image_orig = random.choice(meteors_img)
            self.image_orig.set_colorkey(BLACK)
            self.speedy = random.randrange(5, 15)
        if self.rect.x >= WIDTH:
            self.rect.x = -50
        if self.rect.x <= -51:
            self.rect.x = WIDTH
        self.Rotation()
    def Rotation(self):
        now = pygame.time.get_ticks()
        if now - self.rotation_last_update >= 50:
            self.rotation_last_update = now
            self.rotation = (self.rotation + self.rotation_speed) % 360
            new_image = pygame.transform.rotate(self.image_orig, self.rotation)
            old_center = self.rect.center
            self.image = new_image
            self.rect = self.image.get_rect()
            self.rect.center = old_center
class Bullets(pygame.sprite.Sprite):
    def __init__(self):
        pygame.sprite.Sprite.__init__(self)
        self.image = pygame.Surface((10,15))
        self.image.fill(RED)
        self.rect = self.image.get_rect()
        self.rect.centerx = player.rect.centerx 
        self.rect.centery = HEIGHT - 110
        self.speedx = 0
        self.speedy = -45
    def update(self):
        self.rect.y += self.speedy
        self.rect.x += self.speedx
        if self.rect.y <= 0:
            self.kill()

pygame.init()
pygame.mixer.init()
WIDTH = 600
HEIGHT = 800

fps = 30

cicl = True

WHITE = (255,255,255)
BLACK = (0,0,0)
RED = (255,0,0)
GRAY = (128,128,128)

pygame.display.set_caption("Space shuter")

clock = pygame.time.Clock()

screen = pygame.display.set_mode((WIDTH,HEIGHT))

img_dir = resource_path("images")
img_meteors = resource_path(path.join("images", "Meteors"))

meteors_img = []
for i in range(1,20):
    meteors_img.append(pygame.image.load(path.join(img_meteors,f"{i}.png")).convert())

screen_img = pygame.image.load(path.join(img_dir,"blue.png")).convert()

screen_img = pygame.transform.scale(screen_img, (WIDTH, HEIGHT))

screen_img_rect = screen_img.get_rect()

player_img = pygame.image.load(path.join(img_dir,"player.png")).convert()
#player_img = pygame.transform.scale(player_img, (100, 90))

player = Player()

sprites = pygame.sprite.Group()

sprites.add(player)

mobs = pygame.sprite.Group()

bullets = pygame.sprite.Group()

Score = 0

God = False

for i in range(1,10):
    Mob = Mobs()

    sprites.add(Mob)
    mobs.add(Mob)

while cicl:
    clock.tick(fps)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            cicl = False

    hits = pygame.sprite.spritecollide(player,mobs,False, pygame.sprite.collide_circle)

    if hits:
        cicl = God
        pass

    hits = pygame.sprite.groupcollide(bullets,mobs,True,True)

    for hit in hits:
        Mob = Mobs()
        sprites.add(Mob)
        mobs.add(Mob)
        Score += 1

    sprites.update()

    screen.fill(BLACK)

    screen.blit(screen_img,screen_img_rect)

    sprites.draw(screen)

    draw_text(screen,f"Score:{Score}",45,75,15)
    
    pygame.display.flip()

pygame.quit()
