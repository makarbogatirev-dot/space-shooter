import pygame
import random
from os import path
import numpy as np

font_name = pygame.font.match_font('KenVector Future Regular')

def draw_text(surf,text,size_text,x,y):
    font = pygame.font.Font(font_name, size_text)
    text_surface = font.render(text, True, WHITE)
    text_rect = text_surface.get_rect()
    text_rect.x = x
    text_rect.y = y
    surf.blit(text_surface, text_rect)

def draw_player_health(surf,x,y,hp,size,max_hp):
    global player_health
    if hp < 0:
        hp = 0
    if hp >= 100:
        player_health = 101
    
    bar_length = size
    bar_height = size // 10
    
    fill_width = (hp / max_hp) * bar_length
    
    background_rect = pygame.Rect(x, y, bar_length, bar_height)
    fill_rect = pygame.Rect(x, y, fill_width, bar_height)
    
    pygame.draw.rect(surf, RED, background_rect)
    pygame.draw.rect(surf, GREEN, fill_rect)
    pygame.draw.rect(surf, WHITE, background_rect, 1)

def GodON():
    global God
    God = True
def GodOFF():
    global God
    God = False

def penetrationON():
    global Penetration
    Penetration = True
def penetrationOFF():
    global Penetration
    Penetration = False

def CheatsON():
    GodON()
def CheatsOFF():
    GodOFF()

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
        self.player_health = 100
        self.bonus_time = 0
        self.bonus_speed = False
        self.bonus_god = False
        self.bonus_penetration = False
        self.extra_speed = 0
        self.bonus_god = False
        self.bonus_penetration = False
    def update(self):
        if self.rect.right <= 0:
            self.rect.left = WIDTH
        elif self.rect.left >= WIDTH:
            self.rect.right = 0
        self.speedx = 0
        keystate = pygame.key.get_pressed()
        if keystate[pygame.K_LEFT] or keystate[pygame.K_a]:
            self.speedx = -10 - self.extra_speed
        if keystate[pygame.K_RIGHT] or keystate[pygame.K_d]:
            self.speedx = 10 + self.extra_speed
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
        if self.bonus_god == True:
            self.image = pygame.image.load(path.join(img_dir,"player_god.png")).convert_alpha()
        else:
            self.image = pygame.image.load(path.join(img_dir,"player.png")).convert_alpha()
                
        if self.bonus_speed == True:
            now = pygame.time.get_ticks()
            if now - self.bonus_time <= 10000:
                self.extra_speed = 10
            else:
                self.bonus_speed = False
                self.extra_speed = 0
                
        if self.bonus_god == True:
            now = pygame.time.get_ticks()
            if now - self.bonus_time <= 15000:
                GodON()
            else:
                self.bonus_god = False
                GodOFF()
                
        if self.bonus_penetration == True:
            now = pygame.time.get_ticks()
            if now - self.bonus_time <= 10000:
                penetrationON()
            else:
                self.bonus_penetration = False
                penetrationOFF()
    def create_bullet(self):
        laser_img = pygame.image.load(path.join(img_dir,"laser/laserRed07.png")).convert()
        laser_img.set_colorkey(BLACK)
        now = pygame.time.get_ticks()
        if now - self.last_shoot >= self.shoot_delay:
            bullet = Bullets()
            bullet.image = laser_img
            bullets.add(bullet)
            sprites.add(bullet)
            self.last_shoot = now
            pew_sound.play()
            if self.bonus_penetration == True:
                bullet.image = pygame.image.load(path.join(img_dir,"laser/laserRed16.png")).convert_alpha()
            else:
                bullet.image = pygame.image.load(path.join(img_dir,"laser/laserRed07.png")).convert_alpha()

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

class Explosion(pygame.sprite.Sprite):
    def __init__(self,center,size,width,height):
        pygame.sprite.Sprite.__init__(self)
        self.size = size
        self.image = destroy[self.size][0]
        self.width = width
        self.height = height
        self.image = pygame.transform.scale(self.image, (self.width,self.height))
        self.rect = self.image.get_rect()
        self.rect.center = center
        self.frame = 0
        self.last_update = pygame.time.get_ticks()
        self.frame_rate = 50
    def update(self):
        now = pygame.time.get_ticks()
        if now-self.last_update >= self.frame_rate:
            self.last_update = now
            self.frame += 1
            if self.frame == len(destroy[self.size]):
                self.kill()
            else:
                center = self.rect.center
                self.image = destroy[self.size][self.frame]
                self.image = pygame.transform.scale(self.image, (self.width,self.height))
                self.rect = self.image.get_rect()
                self.rect.center = center

class PowerBonus(pygame.sprite.Sprite):
    def __init__(self,center):
        pygame.sprite.Sprite.__init__(self)
        self.image = pygame.Surface((50,50))
        self.image.fill("GRAY")
        self.types = ["speed","god","penetration"]
        self.probability = [0.65,0.15,0.2]
        self.type = np.random.choice(self.types,size = 1,p = self.probability)
        self.speed = 0
        if self.type == "speed":
            self.speed = 7
            self.image = img_speed
            self.image.set_colorkey(BLACK)
        elif self.type == "god":
            self.speed = 15
            self.image = img_god
            self.image.set_colorkey(BLACK)
        elif self.type == "penetration":
            self.speed = 10
            self.image = img_penetration
            self.image.set_colorkey(WHITE)
            self.image.set_colorkey(BLACK)
        print(self.type)
        self.rect = self.image.get_rect()
        self.rect.center = center
    def update(self):
        self.rect.y += self.speed
        if self.rect.y >= HEIGHT:
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
GREEN = (0, 255, 0)
BLUE = (0,0,255)

pygame.display.set_caption("Space shuter")

clock = pygame.time.Clock()

screen = pygame.display.set_mode((WIDTH,HEIGHT))

img_dir = path.join(path.dirname(__file__),"images")
img_meteors = path.join(path.dirname(__file__),"images/Meteors")
img_bonuses = path.join(path.dirname(__file__),"images/Bonuses")

sound_dir = path.join(path.dirname(__file__),"sounds")
pew_sound = pygame.mixer.Sound(path.join(sound_dir,"pew.wav"))
pew_sound.set_volume(0.1)
meteor_destroy_sound = pygame.mixer.Sound(path.join(sound_dir,"meteor_destroy.wav"))
meteor_destroy_sound.set_volume(0.2)
player_destroy_sound = pygame.mixer.Sound(path.join(sound_dir,"player_destroy.wav"))
player_destroy_sound.set_volume(0.2)
pygame.mixer.music.load(path.join(sound_dir,"music.mp3"))
pygame.mixer.music.set_volume(0.1)

meteors_img = []
for i in range(1,21):
    meteors_img.append(pygame.image.load(path.join(img_meteors,f"{i}.png")).convert())

screen_img = pygame.image.load(path.join(img_dir,"blue.png")).convert()

screen_img = pygame.transform.scale(screen_img, (WIDTH, HEIGHT))

screen_img_rect = screen_img.get_rect()

player_img = pygame.image.load(path.join(img_dir,"player.png")).convert()

player = Player()

player_health = 100

sprites = pygame.sprite.Group()

sprites.add(player)

mobs = pygame.sprite.Group()

bullets = pygame.sprite.Group()

img_animation = path.join(path.dirname(__file__),"images/Meteor destroy animation")

img_speed = pygame.image.load(path.join(img_bonuses,"speed.png")).convert()
img_god = pygame.image.load(path.join(img_bonuses,"god.png")).convert()
img_penetration = pygame.image.load(path.join(img_bonuses,"penetration.png")).convert()

destroy = {}

destroy["small"]=[]
destroy["big"]=[]
for i in range(1,10):
    file_name = "{}.png".format(i)
    img = pygame.image.load(path.join(img_animation,file_name)).convert()
    img.set_colorkey(BLACK)
    img_big = pygame.transform.scale(img, (125,125))
    img_small = pygame.transform.scale(img, (75,75))
    destroy["small"].append(img_small)
    destroy["big"].append(img_big)

Score = 0

God = False

powerups = pygame.sprite.Group()

Penetration = False

Powers = ""

for i in range(1,20):
    Mob = Mobs()

    sprites.add(Mob)
    mobs.add(Mob)

pygame.mixer.music.play(loops=-1)

while cicl:
    clock.tick(fps)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            cicl = False

    hits = pygame.sprite.spritecollide(player,mobs,True, pygame.sprite.collide_circle)

    for hit in hits:
        if not God == True:
            player_health -= 25
        Mob = Mobs()
        sprites.add(Mob)
        mobs.add(Mob)
        meteor_destroy_sound.play()
        expule = Explosion(player.rect.center,"big",85,85)
        sprites.add(expule)
        if God == False:
            player_destroy_sound.play()
        if player_health <= 0:
            cicl = God

    if Penetration == True:
        hits = pygame.sprite.groupcollide(bullets,mobs,False,True)
    if Penetration == False:
        hits = pygame.sprite.groupcollide(bullets,mobs,True,True)

    for hit in hits:
        Mob = Mobs()
        sprites.add(Mob)
        mobs.add(Mob)
        meteor_destroy_sound.play()
        Score += 1
        expule = Explosion(hit.rect.center,"small",85,85)
        sprites.add(expule)
        if random.random() > 0.99:
            power = PowerBonus(hit.rect.center)
            sprites.add(power)
            powerups.add(power)

    hits = pygame.sprite.spritecollide(player,powerups,True)

    for hit in hits:
        player.bonus_time = pygame.time.get_ticks()
        print("Выдача силы!")
        if hit.type == "speed":
            player.bonus_speed = True
            print(hit.type)
        elif hit.type == "god":
            player.bonus_god = True
            player_health += 25
            print(hit.type)
        elif hit.type == "penetration":
            player.bonus_penetration = True
            print(hit.type)
        

    sprites.update()

    screen.fill(BLACK)

    screen.blit(screen_img,screen_img_rect)

    sprites.draw(screen)

    draw_text(screen,f"Score:{Score}",35,25,15)

    #draw_text(screen,f"Powers:{Powers}",20,25,55)

    if player.bonus_speed == True:
        draw_text(screen,f"Speed",20,25,55)
    if player.bonus_god == True:
        draw_text(screen,f"God",20,25,70)
    if player.bonus_penetration == True:
        draw_text(screen,f"Penetration",20,25,85)

    draw_player_health(screen,375,20,player_health,185,100)
    
    pygame.display.flip()

pygame.quit()
