"""Best-effort code.py integration smoke with fake Pico modules.
Run separately: python tests/smoke_firmware_mock.py
Not a substitute for hardware validation.
"""
from pathlib import Path
import builtins
import importlib
import json
import runpy
import sys
import types
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'CIRCUITPY'))
orig_open=builtins.open

def mapped_open(path,*a,**kw):
    if str(path)=='/settings.json': path=str(ROOT/'CIRCUITPY'/'settings.example.json')
    return orig_open(path,*a,**kw)

class Clock:
    now=0.0
    def monotonic(self): return self.now
    def sleep(self,dt):
        self.now+=dt
        if self.now>3.0: raise SystemExit('smoke completed')
clock=Clock()

class Radio:
    connected=False
    hostname=''
    ipv4_address=None
    connects=0
    def connect(self, ssid,password,*,timeout=None):
        assert timeout==3
        self.connected=True
        self.ipv4_address='192.0.2.88'
        self.connects+=1
radio=Radio()

class PWMOut:
    def __init__(self,*a,**kw): self.duty_cycle=kw.get('duty_cycle',0)

class MPRLS:
    def __init__(self,*a,**kw): self.reads=0
    @property
    def pressure(self): self.reads+=1;return 949.865

class Watchdog:
    timeout=0;mode=None;feeds=0
    def feed(self):self.feeds+=1
wd=Watchdog()

class Request:
    pass
class Response:
    def __init__(self,request,body='',**kw):self.body=body;self.kw=kw
class Server:
    routes={}
    polls=0
    def __init__(self,pool,debug=False):self.socket_timeout=None
    def route(self,path,method):
        def deco(fn):self.routes[(path,method)]=fn;return fn
        return deco
    def start(self,host,port):assert port==80;assert host=='192.0.2.88'
    def poll(self):
        type(self).polls+=1
        if type(self).polls==1:
            page=self.routes[('/', 'GET')](Request()).body
            assert 'NORMAL' in page
            assert '950.156' in page
            status=json.loads(self.routes[('/status.json','GET')](Request()).body)
            assert status['state']=='NORMAL'
            assert status['wifi_connected']
            ack=self.routes[('/ack','POST')](Request()).body
            assert 'acknowledged' in ack
    def stop(self):pass

mods={}
def add(name,**kwargs):
    m=types.ModuleType(name)
    for k,v in kwargs.items():setattr(m,k,v)
    mods[name]=m
    return m
add('board',GP12=12,GP13=13,GP15=15,GP16=16,GP2=2)
add('busio',I2C=lambda **kwargs:object())
add('digitalio',DigitalInOut=lambda p:object())
add('pwmio',PWMOut=PWMOut)
add('socketpool',SocketPool=lambda radio:object())
add('wifi',radio=radio)
add('adafruit_mprls',MPRLS=MPRLS)
add('microcontroller',cpu=types.SimpleNamespace(reset_reason='POWER_ON'),watchdog=wd,reset=lambda:None)
add('watchdog',WatchDogMode=types.SimpleNamespace(RESET='RESET'))
add('adafruit_httpserver',GET='GET',POST='POST',Request=Request,Response=Response,Server=Server)
add('time',monotonic=clock.monotonic,sleep=clock.sleep)
add('gc',collect=lambda:None,mem_free=lambda:80000,mem_alloc=lambda:50000)

cfg=json.loads((ROOT/'CIRCUITPY'/'settings.example.json').read_text())
assert cfg['ssid']==''
# The packaged firmware intentionally leaves Wi-Fi unconfigured. Supply fake
# credentials IN MEMORY to test the HTTP path without distributing secrets.
import io

def wifi_test_open(path,*a,**kw):
    if str(path)=='/settings.json':
        val=dict(cfg,ssid='SMOKE_TEST',wifi_pwd='test-password')
        return io.StringIO(json.dumps(val))
    return orig_open(path,*a,**kw)

with patch.dict(sys.modules,mods),patch.object(builtins,'open',wifi_test_open):
    try:runpy.run_path(str(ROOT/'CIRCUITPY'/'code.py'),run_name='__main__')
    except SystemExit:pass

assert radio.connects==1
assert wd.feeds>20
print("polls",Server.polls,"feeds",wd.feeds,"t",clock.now)
assert Server.polls>2
print('MOCK FIRMWARE SMOKE PASSED: sensor sampling, watchdog, Wi-Fi, HTTP HTML/JSON/ACK routes')
