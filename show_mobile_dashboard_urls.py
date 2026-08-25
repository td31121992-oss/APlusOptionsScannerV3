import socket

def get_ips():
    found=set()
    try:
        host=socket.gethostname()
        for x in socket.getaddrinfo(host,None,socket.AF_INET):
            ip=x[4][0]
            if not ip.startswith("127."):
                found.add(ip)
    except Exception:
        pass
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80))
        found.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(found)

print("="*72)
print("APlus Mobile Dashboard URLs")
print("="*72)
ips=get_ips()
for ip in ips:
    print(f"Main dashboard   : http://{ip}:8765")
    print(f"Technical alerts : http://{ip}:8766")
    print()
if not ips:
    print("Could not auto-detect LAN IP. Run: ipconfig")
print("Phone and laptop must be on the same Wi-Fi/local network.")
print("="*72)
