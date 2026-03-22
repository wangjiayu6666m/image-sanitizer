from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from PIL import Image, ImageFilter
import numpy as np
import io
import struct
import random
import math

app = Flask(__name__)
CORS(app)

MAX_FILE_SIZE = 20 * 1024 * 1024
ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/bmp'}

# ── Metadata ────────────────────────────────────────────────────────────────

def strip_exif(img):
    data = img.tobytes()
    return Image.frombytes(img.mode, img.size, data)

def strip_png_chunks(data):
    KEEP = {b'IHDR', b'IDAT', b'IEND', b'PLTE', b'tRNS'}
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return data
    result = bytearray(data[:8])
    pos = 8
    while pos + 12 <= len(data):
        length = struct.unpack('>I', data[pos:pos+4])[0]
        chunk_type = data[pos+4:pos+8]
        if chunk_type in KEEP:
            result.extend(data[pos:pos+12+length])
        pos += 12 + length
    return bytes(result)

# ── PRNU / sensor fingerprint attack ────────────────────────────────────────

def prnu_attack(img, passes=3, sigma=2.5):
    """
    Multi-pass rotation + noise to destroy camera sensor fingerprint.
    Each pass uses a different random sub-pixel rotation so the PRNU
    pattern de-correlates across passes.
    """
    for _ in range(passes):
        angle = random.uniform(-0.8, 0.8)
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False)
        arr = np.array(img, dtype=np.float32)
        arr += np.random.normal(0, sigma, arr.shape)
        # Whole-image gamma tweak (same for all channels to avoid colour cast)
        arr = np.clip(arr, 1, 255)
        g = random.uniform(0.97, 1.03)
        arr = np.power(arr / 255.0, g) * 255.0
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return img

# ── Robust watermark attack ──────────────────────────────────────────────────

def geometric_attack(img):
    """
    Slight crop + resize destroys geometric watermarks and edge-embedded marks.
    Also applies a tiny random perspective warp via numpy (no external deps).
    """
    w, h = img.size
    # Crop 2% from each edge
    margin_x = max(2, int(w * 0.02))
    margin_y = max(2, int(h * 0.02))
    img = img.crop((margin_x, margin_y, w - margin_x, h - margin_y))
    img = img.resize((w, h), Image.LANCZOS)

    # Row/col micro-shift (breaks periodic watermarks)
    arr = np.array(img, dtype=np.float32)
    for row in range(0, arr.shape[0], random.randint(8, 16)):
        shift = random.randint(-1, 1)
        if shift != 0:
            arr[row] = np.roll(arr[row], shift, axis=0)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

def frequency_attack(img, quality=72):
    """Double JPEG recompress at two different quality levels."""
    def recompress(im, q):
        buf = io.BytesIO()
        if im.mode in ('RGBA', 'P'):
            im = im.convert('RGB')
        im.save(buf, format='JPEG', quality=q, optimize=True, subsampling=2)
        buf.seek(0)
        return Image.open(buf).copy()

    img = recompress(img, quality)
    img = recompress(img, min(quality + 8, 92))
    return img

# ── LSB / steganography attack ───────────────────────────────────────────────

def lsb_attack(img, strength=2.0):
    arr = np.array(img, dtype=np.float32)
    # Targeted LSB destruction: zero bottom 2 bits then re-randomise
    arr_int = arr.astype(np.uint8)
    arr_int = (arr_int & 0b11111100) | np.random.randint(0, 4, arr_int.shape, dtype=np.uint8)
    # Add Gaussian noise on top
    result = arr_int.astype(np.float32) + np.random.normal(0, strength, arr_int.shape)
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))

# ── Resample ──────────────────────────────────────────────────────────────────

def resample_attack(img, scale=0.75):
    w, h = img.size
    small = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return small.resize((w, h), Image.LANCZOS)

# ── MAX mode pipeline ─────────────────────────────────────────────────────────

def max_sanitize(img):
    """
    Full journalist-grade pipeline:
    1. EXIF strip (already done before this call)
    2. Geometric attack  — robust/edge watermarks
    3. PRNU attack x3    — sensor fingerprint
    4. LSB destruction   — steganographic marks
    5. Resample 70%      — pixel-level watermarks
    6. Frequency attack  — DCT-domain watermarks (double JPEG)
    7. Final noise pass  — catch anything remaining
    """
    steps = []

    img = geometric_attack(img)
    steps.append('Geometric attack')

    img = prnu_attack(img, passes=3, sigma=2.5)
    steps.append('PRNU attack (3-pass)')

    img = lsb_attack(img, strength=2.0)
    steps.append('LSB destruction')

    img = resample_attack(img, scale=0.70)
    steps.append('Resample attack (70%)')

    img = frequency_attack(img, quality=72)
    steps.append('Frequency attack (double JPEG)')

    # Final light noise pass
    arr = np.array(img, dtype=np.float32)
    arr += np.random.normal(0, 1.2, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    steps.append('Final noise sweep')

    return img, steps

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/sanitize', methods=['POST'])
def sanitize():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400
    if file.content_type not in ALLOWED_TYPES:
        return jsonify({'error': f'Unsupported type: {file.content_type}'}), 400

    raw = file.read()
    if len(raw) > MAX_FILE_SIZE:
        return jsonify({'error': 'File exceeds 20MB'}), 400

    mode = request.form.get('mode', 'custom')  # 'max' or 'custom'
    output_format = request.form.get('output_format', 'png').upper()
    if output_format == 'JPG':
        output_format = 'JPEG'

    steps_done = []

    try:
        # Always strip PNG chunks at byte level first
        if file.content_type == 'image/png':
            raw = strip_png_chunks(raw)
            steps_done.append('PNG chunk strip')

        img = Image.open(io.BytesIO(raw))
        if img.mode not in ('RGB', 'RGBA', 'L'):
            img = img.convert('RGB')
        if img.mode == 'L':
            img = img.convert('RGB')

        # Always strip EXIF
        img = strip_exif(img)
        steps_done.append('EXIF strip')

        if mode == 'max':
            img, extra_steps = max_sanitize(img)
            steps_done.extend(extra_steps)
        else:
            # Custom mode — individual toggles
            options = {
                'noise':          request.form.get('noise', 'true') == 'true',
                'noise_strength': float(request.form.get('noise_strength', '1.5')),
                'resample':       request.form.get('resample', 'true') == 'true',
                'resample_scale': float(request.form.get('resample_scale', '0.75')),
                'jpeg_recompress':request.form.get('jpeg_recompress', 'true') == 'true',
                'jpeg_quality':   int(request.form.get('jpeg_quality', '82')),
                'prnu_attack':    request.form.get('prnu_attack', 'false') == 'true',
                'geometric':      request.form.get('geometric', 'false') == 'true',
                'lsb_destroy':    request.form.get('lsb_destroy', 'false') == 'true',
            }
            if options['geometric']:
                img = geometric_attack(img)
                steps_done.append('Geometric attack')
            if options['prnu_attack']:
                img = prnu_attack(img, passes=3, sigma=2.5)
                steps_done.append('PRNU attack (3-pass)')
            if options['lsb_destroy']:
                img = lsb_attack(img, options['noise_strength'])
                steps_done.append('LSB destruction')
            elif options['noise']:
                arr = np.array(img)
                arr = (np.array(img, dtype=np.float32) +
                       np.random.normal(0, options['noise_strength'], np.array(img).shape))
                img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
                steps_done.append(f'Noise injection (sigma={options["noise_strength"]})')
            if options['resample']:
                img = resample_attack(img, options['resample_scale'])
                steps_done.append(f'Resample attack ({int(options["resample_scale"]*100)}%)')
            if options['jpeg_recompress']:
                img = frequency_attack(img, options['jpeg_quality'])
                steps_done.append(f'JPEG recompress (q={options["jpeg_quality"]})')

        # Output
        if output_format == 'JPEG' and img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        out_buf = io.BytesIO()
        jpeg_quality = int(request.form.get('jpeg_quality', '82'))
        if output_format == 'JPEG':
            img.save(out_buf, format='JPEG', quality=jpeg_quality, optimize=True)
        elif output_format == 'PNG':
            img.save(out_buf, format='PNG', optimize=True)
        else:
            img.save(out_buf, format=output_format)
        out_buf.seek(0)

        mime_map = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}
        mime = mime_map.get(output_format, 'image/png')

        from urllib.parse import quote
        resp = send_file(out_buf, mimetype=mime, as_attachment=True,
                         download_name=f'sanitized.{output_format.lower()}')
        resp.headers['X-Steps-Done'] = quote(', '.join(steps_done))
        resp.headers['X-Steps-Count'] = str(len(steps_done))
        return resp

    except Exception as e:
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

# ── Analysis route ────────────────────────────────────────────────────────────

@app.route('/analyze', methods=['POST'])
def analyze():
    """Compare original vs sanitized image and return metrics."""
    if 'original' not in request.files or 'sanitized' not in request.files:
        return jsonify({'error': 'Need both original and sanitized files'}), 400

    orig_file = request.files['original']
    san_file  = request.files['sanitized']

    try:
        orig_raw = orig_file.read()
        san_raw  = san_file.read()

        orig_img = Image.open(io.BytesIO(orig_raw)).convert('RGB')
        san_img  = Image.open(io.BytesIO(san_raw)).convert('RGB')

        orig_arr = np.array(orig_img, dtype=np.float32)
        san_arr  = np.array(san_img,  dtype=np.float32)

        results = {}

        # ── EXIF check ────────────────────────────────────────────────────
        def exif_fields(raw_bytes):
            try:
                img = Image.open(io.BytesIO(raw_bytes))
                exif = img._getexif() if hasattr(img, '_getexif') else None
                if exif:
                    return len(exif)
            except Exception:
                pass
            return 0

        orig_exif_count = exif_fields(orig_raw)
        san_exif_count  = exif_fields(san_raw)
        results['exif'] = {
            'original_fields': orig_exif_count,
            'sanitized_fields': san_exif_count,
            'cleared': san_exif_count == 0,
        }

        # ── LSB analysis ─────────────────────────────────────────────────
        orig_lsb = (orig_arr.astype(np.uint8) & 1).astype(np.float32)
        san_lsb  = (san_arr.astype(np.uint8)  & 1).astype(np.float32)

        def lsb_correlation(lsb_plane):
            flat = lsb_plane[:, :, 0].flatten()
            if len(flat) < 2:
                return 0.0
            c = np.corrcoef(flat[:-1], flat[1:])[0, 1]
            return float(c) if not np.isnan(c) else 0.0

        results['lsb'] = {
            'original_mean':    round(float(orig_lsb.mean()), 4),
            'sanitized_mean':   round(float(san_lsb.mean()),  4),
            'original_corr':    round(lsb_correlation(orig_lsb), 4),
            'sanitized_corr':   round(lsb_correlation(san_lsb),  4),
            'destroyed': abs(float(san_lsb.mean()) - 0.5) < 0.05,
        }

        # ── PRNU sensor fingerprint ───────────────────────────────────────
        from PIL import ImageFilter

        def prnu_residual(pil_img):
            gray = pil_img.convert('L')
            blur = gray.filter(ImageFilter.GaussianBlur(2))
            return (np.array(gray, dtype=np.float32) -
                    np.array(blur, dtype=np.float32)).flatten()

        n_orig = prnu_residual(orig_img)
        n_san  = prnu_residual(san_img)
        min_len = min(len(n_orig), len(n_san))
        prnu_corr = float(np.corrcoef(n_orig[:min_len], n_san[:min_len])[0, 1])
        if np.isnan(prnu_corr):
            prnu_corr = 0.0

        results['prnu'] = {
            'correlation': round(prnu_corr, 6),
            'destroyed': abs(prnu_corr) < 0.005,
            'level': (
                'Strong fingerprint' if abs(prnu_corr) > 0.02 else
                'Weak fingerprint'   if abs(prnu_corr) > 0.005 else
                'Fingerprint destroyed'
            ),
        }

        # ── Pixel difference ──────────────────────────────────────────────
        same_size = orig_arr.shape == san_arr.shape
        if same_size:
            diff = np.abs(orig_arr - san_arr)
            identical_pct = float((diff.sum(axis=2) == 0).mean() * 100)
            results['pixel_diff'] = {
                'mean':           round(float(diff.mean()), 3),
                'max':            int(diff.max()),
                'identical_pct':  round(identical_pct, 1),
                'adequate':       float(diff.mean()) > 2.0,
            }
        else:
            results['pixel_diff'] = {
                'mean': None, 'max': None,
                'identical_pct': None, 'adequate': None,
                'note': 'Different dimensions'
            }

        # ── Overall verdict ───────────────────────────────────────────────
        checks = [
            results['exif']['cleared'],
            results['lsb']['destroyed'],
            results['prnu']['destroyed'],
            results['pixel_diff'].get('adequate', False),
        ]
        passed = sum(1 for c in checks if c)
        results['verdict'] = {
            'passed': passed,
            'total':  len(checks),
            'grade': 'PASS' if passed >= 3 else 'PARTIAL' if passed >= 2 else 'FAIL',
        }

        return jsonify(results)

    except Exception as e:
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500
