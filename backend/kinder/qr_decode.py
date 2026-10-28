"""Fixed-purpose, resource-bounded QR decoder. Input/output stay in memory pipes."""
import io
import re
import resource
import sys
import warnings


def main():
    resource.setrlimit(resource.RLIMIT_AS,(384*1024*1024,384*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(2,2))
    resource.setrlimit(resource.RLIMIT_NOFILE,(32,32))
    from PIL import Image
    import zxingcpp
    Image.MAX_IMAGE_PIXELS=4000000
    warnings.simplefilter('error',Image.DecompressionBombWarning)
    raw=sys.stdin.buffer.read(2097153)
    if len(raw)>2097152:return 2
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG','JPEG') or not 50<=image.width<=2048 or not 50<=image.height<=2048 or image.width*image.height>4000000:return 2
            values=zxingcpp.read_barcodes(image.convert('L'),formats=zxingcpp.BarcodeFormat.QRCode)
        if len(values)!=1 or not re.fullmatch(r'[A-Za-z0-9_-]{43}',values[0].text):return 2
        sys.stdout.write(values[0].text)
        return 0
    except Exception:return 2


if __name__=='__main__':
    raise SystemExit(main())
