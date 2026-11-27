from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from .control_store import FEATURES,LIMITS

class Model(BaseModel):model_config=ConfigDict(extra='forbid')
class Plan(Model):
 id:str=Field(pattern=r'^[a-z][a-z0-9_-]{1,40}$')
 title_ar:str=Field(min_length=1,max_length=100);title_en:str=Field(min_length=1,max_length=100)
 description_ar:str=Field(default='',max_length=1200);description_en:str=Field(default='',max_length=1200)
 price_iqd:int=Field(ge=0,le=100000000);days:int=Field(default=30,ge=1,le=366)
 enabled:bool=False;features:dict[str,bool];limits:dict[str,int];version:int=Field(default=0,ge=0)
 @model_validator(mode='after')
 def check(self):
  if set(self.features)!=set(FEATURES) or set(self.limits)!=set(LIMITS) or any(type(v)!=int or not 0<=v<=100000 for v in self.limits.values()):raise ValueError('Supply every known feature and limit')
  if self.id=='free' and (self.price_iqd or not self.enabled):raise ValueError('Free plan must remain enabled and free')
  return self
class Membership(Model):
 plan_id:str;days:int=Field(default=30,ge=1,le=3660);reason:str=Field(min_length=3,max_length=500)
class UserChange(Model):
 confirm_password:str=Field(default='',max_length=128)
 disabled:bool;role:Literal['user','admin'];reason:str=Field(min_length=3,max_length=500)
class Discount(Model):
 code:str=Field(pattern=r'^[A-Z0-9_-]{3,32}$');kind:Literal['percent','fixed'];value:int=Field(ge=1,le=100000000)
 enabled:bool=False;starts_at:float=Field(ge=0);ends_at:float=Field(gt=0);max_uses:int=Field(ge=1,le=1000000);per_user:int=Field(default=1,ge=1,le=1000);plan_id:str|None=None;version:int=Field(default=0,ge=0)
 @model_validator(mode='after')
 def check(self):
  if self.ends_at<=self.starts_at or self.kind=='percent' and self.value>100:raise ValueError('Invalid percentage or dates')
  return self
EVENTS=('home_visit','knowledge_visit','play_visit','login','lesson_complete','puzzle_solved','game_finished','review_opened')
BANNER_PLACEMENTS=('screen_top','screen_bottom','screen_left','screen_right')
BANNER_VIEWS=('home','games','knowledge','learning','play','grades','course')
class AdvertisingSettings(Model):
 enabled:bool=True
 slots:dict[str,bool]=Field(default_factory=lambda:{p:True for p in BANNER_PLACEMENTS})
 side_min_width:Literal[1800,1920,2200]=1800
 max_active:int=Field(default=4,ge=1,le=4)
 google_enabled:bool=False
 google_client:str=Field(default='',pattern=r'^(|ca-pub-[0-9]{16})$')
 google_consent_ready:bool=False
 dismiss_hours:int=Field(default=24,ge=1,le=168)
 version:int=Field(default=0,ge=0)
 confirm_password:str=Field(default='',max_length=128)
 @model_validator(mode='after')
 def check(self):
  if set(self.slots)!=set(BANNER_PLACEMENTS):raise ValueError('Supply all four banner placements')
  if self.google_enabled and (not self.google_client or not self.google_consent_ready):raise ValueError('Supply the AdSense publisher ID and configure your certified consent platform before enabling Google ads')
  return self
class BannerContext(Model):
 view:Literal['home','games','knowledge','learning','play','grades','course']
 width:int=Field(ge=0,le=20000)
 visit:str=Field(min_length=1,max_length=100,pattern=r'^[a-zA-Z0-9:_-]+$')
class CampaignState(Model):
 action:Literal['activate','pause','show','hide']
 version:int=Field(ge=1)
class Campaign(Model):
 id:str=Field(default='',pattern=r'^(|[a-f0-9]{32})$');title_ar:str=Field(min_length=1,max_length=160);title_en:str=Field(min_length=1,max_length=160)
 body_ar:str=Field(default='',max_length=2000);body_en:str=Field(default='',max_length=2000)
 image_path:str=Field(default='',pattern=r'^(|/api/promotions/media/[a-f0-9]{32}\.(png|jpg|webp))$')
 link_url:str=Field(default='',max_length=1500);button_ar:str=Field(default='اعرف المزيد',max_length=60);button_en:str=Field(default='Learn more',max_length=60)
 placement:Literal['home_top','knowledge_top','play_top','modal','screen_top','screen_bottom','screen_left','screen_right']='home_top';event:Literal['home_visit','knowledge_visit','play_visit','login','lesson_complete','puzzle_solved','game_finished','review_opened']='home_visit'
 kind:Literal['custom','adsense']='custom'
 visible:bool=True;dismissible:bool=True
 views:list[Literal['home','games','knowledge','learning','play','grades','course']]=Field(default_factory=lambda:['home','games','knowledge','learning'],min_length=1,max_length=7)
 adsense_slot:str=Field(default='',pattern=r'^(|[0-9]{5,20})$')
 image_fit:Literal['contain','cover']='contain'
 alt_ar:str=Field(default='',max_length=240);alt_en:str=Field(default='',max_length=240)
 after_n:int=Field(default=1,ge=1,le=1000);daily_cap:int=Field(default=1,ge=1,le=10);cooldown_minutes:int=Field(default=1440,ge=1,le=525600)
 plan_id:str|None=None;enabled:bool=False;starts_at:float=Field(ge=0);ends_at:float=Field(gt=0);priority:int=Field(default=0,ge=0,le=100);version:int=Field(default=0,ge=0)
 @field_validator('link_url')
 @classmethod
 def url(cls,v):
  if not v:return v
  if any(ord(c)<32 for c in v) or '\\' in v:raise ValueError('Invalid link')
  p=urlsplit(v)
  if v.startswith('/') and not v.startswith('//'):return v
  if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Use HTTPS or an internal path')
  return v
 @model_validator(mode='after')
 def check(self):
  if self.ends_at<=self.starts_at:raise ValueError('Invalid campaign dates')
  expected={'home_top':'home_visit','knowledge_top':'knowledge_visit','play_top':'play_visit'}
  if self.placement in expected and self.event!=expected[self.placement]:raise ValueError('Banner event must match its placement')
  if len(self.views)!=len(set(self.views)):raise ValueError('Duplicate audience views')
  if self.kind=='adsense' and (self.placement not in BANNER_PLACEMENTS or not self.adsense_slot):raise ValueError('Google ads require a manual banner placement and AdSense slot ID')
  if self.kind=='adsense' and (self.image_path or self.link_url):raise ValueError('Google manages its own creative and destination; remove the custom image and link')
  return self
class SiteSettings(Model):
 site_name:str=Field(min_length=1,max_length=80);tagline_ar:str=Field(max_length=200);tagline_en:str=Field(max_length=200);support_email:str=Field(default='',max_length=255)
 ai_enabled:bool=True
 maintenance:bool=False;maintenance_ar:str=Field(min_length=1,max_length=500);maintenance_en:str=Field(min_length=1,max_length=500)
 daily_enabled:bool=True;daily_target:int=Field(default=24,ge=21,le=48)
class ProviderSettings(Model):
 enabled:bool=True
 confirm_password:str=Field(default='',max_length=128)
 primary:Literal['groq','xai','openrouter','openai'];fallback:list[Literal['groq','xai','openrouter','openai']]=Field(default_factory=list,max_length=3)
 models:dict[str,str];keys:dict[str,str]=Field(default_factory=dict)
 @model_validator(mode='after')
 def check(self):
  names=[self.primary]+self.fallback
  known={'groq','xai','openrouter','openai'}
  if len(names)!=len(set(names)) or not set(names)<=set(self.models) or not set(self.models)<=known or not set(self.keys)<=known:raise ValueError('Provider order and models must match')
  if any(not self.models.get(n,'').strip() or len(self.models[n])>160 for n in set(names)|set(self.keys)):raise ValueError('Supply a model for each selected provider or new key')
  return self
class Gateway(Model):
 confirm_password:str=Field(default='',max_length=128)
 enabled:bool=False;environment:Literal['sandbox','live']='sandbox';public:dict=Field(default_factory=dict);secrets:dict[str,str]=Field(default_factory=dict)
class Checkout(Model):
 plan_id:str;gateway:Literal['zaincash','fib'];discount_code:str=Field(default='',max_length=32);request_key:str=Field(pattern=r'^[a-zA-Z0-9_-]{16,80}$')
class AdEvent(Model):
 event:Literal['home_visit','knowledge_visit','play_visit','login','lesson_complete','puzzle_solved','game_finished','review_opened'];resource:str=Field(min_length=1,max_length=100)
class PlayPurchase(Model):
 purchase_token:str=Field(min_length=10,max_length=4096);product_id:str=Field(min_length=1,max_length=150)
