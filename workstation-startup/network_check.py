"""Direct, certificate-validated Internet checks. No proxy or portal redirects."""
import socket
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):return None


def is_online(timeout=5):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    probes=(('https://www.msftconnecttest.com/connecttest.txt','ncsi'),
            ('https://www.baidu.com/','html'))
    for url,kind in probes:
        try:
            request=urllib.request.Request(url,headers={'Cache-Control':'no-cache','User-Agent':'CampusNetworkMonitor/1.0'})
            with opener.open(request,timeout=timeout) as response:
                data=response.read(32768)
                if response.status!=200:continue
                if kind=='ncsi' and data.strip()==b'Microsoft Connect Test':return True
                if kind=='html' and b'<html' in data.lower():return True
        except Exception:
            continue
    return False


def portal_reachable(timeout=3):
    try:
        with socket.create_connection(('172.16.253.3',80),timeout=timeout):return True
    except OSError:return False
