"""Mocked CircuitPython integration smoke (NOT an actual hardware validation)."""
from pathlib import Path
import builtins
import io
import json
import runpy
import sys
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'CIRCUITPY'))
real_open = builtins.open

class Clock:
    now = 0.0
    def monotonic(self): return self.now
    def sleep(self, dt):
        self.now += dt
        if self.now > 3: raise SystemExit('smoke completed')
clock = Clock()

class Radio:
    connected = False
    hostname = ''
    ipv4_address = None
    connects = 0
    def connect(self, ssid, password, *, timeout=None):
        assert timeout == 3
        self.connected = True
        self.ipv4_address = '192.0.2.88'
        self.connects += 1
radio = Radio()

class PWMOut:
    def __init__(self, *a, **kw): self.duty_cycle=kw.get('duty_cycle',0)

class MPRLS:
    reads=0
    def __init__(self, *a, **kw): pass
    @property
    def pressure(self):
        type(self).reads += 1
        return 949.865

class BME280:
    reads=0
    def __init__(self, i2c, address): assert address == 119
    @property
    def pressure(self):
        type(self).reads += 1
        return 952.776
    @property
    def temperature(self): return 23.4
    @property
    def relative_humidity(self): return 37.0

class Watchdog:
    timeout=0;mode=None;feeds=0
    def feed(self):self.feeds+=1
wd=Watchdog()

class Request: pass
class Response:
    def __init__(self,request,body='',**kw):self.body=body
class Server:
    routes={}
    polls=0
    def __init__(self,pool,debug=False):self.socket_timeout=None
    def route(self,path,method):
        def deco(fn):self.routes[(path,method)]=fn;return fn
        return deco
    def start(self,host,port):assert port==80 and host=='192.0.2.88'
    def poll(self):
        type(self).polls+=1
        if type(self).polls==1:
            page=self.routes[('/', 'GET')](Request()).body
            assert 'NORMAL' in page
            assert '2.911' in page
            assert 'BME280' in page
            status=json.loads(self.routes[('/status.json','GET')](Request()).body)
            assert status['state']=='NORMAL'
            assert status['wifi_connected']
            assert status['measurement_type'].startswith('offset_corrected')
            assert status['room_temperature_c']==23.4
            ack=self.routes[('/ack','POST')](Request()).body
            assert 'acknowledged' in ack
    def stop(self):pass

mods={}
def add(name,**kwargs):
    module=types.ModuleType(name)
    for k,v in kwargs.items():setattr(module,k,v)
    mods[name]=module
    return module
add('board',GP12=12,GP13=13,GP15=15,GP16=16,GP2=2)
add('busio',I2C=lambda **kwargs:object())
add('digitalio',DigitalInOut=lambda p:object())
add('pwmio',PWMOut=PWMOut)
add('socketpool',SocketPool=lambda radio:object())
add('wifi',radio=radio)
add('adafruit_mprls',MPRLS=MPRLS)
add('adafruit_bme280',basic=types.SimpleNamespace(Adafruit_BME280_I2C=BME280))
add('microcontroller',cpu=types.SimpleNamespace(reset_reason='POWER_ON'),watchdog=wd,reset=lambda:None)
add('watchdog',WatchDogMode=types.SimpleNamespace(RESET='RESET'))
add('adafruit_httpserver',GET='GET',POST='POST',Request=Request,Response=Response,Server=Server)
add('time',monotonic=clock.monotonic,sleep=clock.sleep)
add('gc',collect=lambda:None,mem_free=lambda:80000,mem_alloc=lambda:50000)

cfg=json.loads((ROOT/'CIRCUITPY'/'settings.example.json').read_text())
assert cfg['ssid']=='' and cfg['calibration_stage']=='zero'
# Test monitoring without storing live passwords or skipping explicit device calibration.
ready=dict(cfg,ssid='TEST_ONLY',wifi_pwd='never-deploy',calibration_stage='ready',
           sensor_offset_hpa=0,baseline_suction_hpa=2.911)

def test_open(path,*a,**kw):
    if str(path)=='/settings.json':return io.StringIO(json.dumps(ready))
    return real_open(path,*a,**kw)

with patch.dict(sys.modules,mods), patch.object(builtins,'open',test_open):
    try:runpy.run_path(str(ROOT/'CIRCUITPY'/'code.py'),run_name='__main__')
    except SystemExit:pass

assert radio.connects==1 and wd.feeds>20
assert Server.polls>2
assert MPRLS.reads>=1 and BME280.reads>=1
print('MOCK FIRMWARE SMOKE PASSED: paired sensors, watchdog, Wi-Fi, HTTP, JSON, acknowledgment')
