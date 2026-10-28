"""Native acceptance gate: real APK, JVM and emulator XML, synthetic screenshots."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'android/app/build'
OUT=ROOT/'android-evidence'
OUT.mkdir(exist_ok=True)


def require(value,code):
    if not value:raise RuntimeError(code)


def junit(folder,expected):
    paths=sorted(folder.rglob('TEST-*.xml'))
    require(bool(paths),'native_test_xml_missing')
    totals={'tests':0,'failures':0,'errors':0,'skipped':0}
    for path in paths:
        root=ET.parse(path).getroot()
        require(root.tag=='testsuite','native_test_shape_changed')
        for key in totals:totals[key]+=max(int(root.get(key,'0')),len(root.findall('.//skipped')) if key=='skipped' else 0)
    require(totals=={'tests':expected,'failures':0,'errors':0,'skipped':0},'native_tests_not_accepted')
    return totals


try:
    unit=junit(APP/'test-results/testReviewDebugUnitTest',16)
    fixture=junit(APP/'outputs/androidTest-results/connected/debug/flavors/fixture',10)
    review=junit(APP/'outputs/androidTest-results/connected/debug/flavors/review',1)
    apk=APP/'outputs/apk/review/debug/app-review-debug.apk'
    require(apk.is_file() and 10000<apk.stat().st_size<20*1024*1024,'review_apk_missing_or_oversize')
    sdk=Path(os.environ.get('ANDROID_HOME',os.environ.get('ANDROID_SDK_ROOT','/workspace/android-sdk')))
    aapt=sdk/'build-tools/36.0.0/aapt'
    permissions=subprocess.check_output([str(aapt),'dump','permissions',str(apk)],text=True)
    require([line for line in permissions.splitlines() if line.startswith('uses-permission:')]==["uses-permission: name='android.permission.INTERNET'"],'unexpected_app_permission')
    manifest=subprocess.check_output([str(aapt),'dump','xmltree',str(apk),'AndroidManifest.xml'],text=True)
    badging=subprocess.check_output([str(aapt),'dump','badging',str(apk)],text=True)
    require("sdkVersion:'26'" in badging and "targetSdkVersion:'36'" in badging,'review_sdk_contract_changed')
    subprocess.run([str(sdk/'build-tools/36.0.0/apksigner'),'verify',str(apk)],check=True,capture_output=True)
    require('uz.kinderspa.client.review' in manifest and 'usesCleartextTraffic' in manifest and 'allowBackup' in manifest,'review_manifest_identity_missing')
    for line in manifest.splitlines():
        if any(key in line for key in ('usesCleartextTraffic','allowBackup')):require(re.search(r'\(type 0x12\)0x0(?:\s|$)',line) is not None,'review_privacy_manifest_changed')
    target=OUT/'kinder-spa-review-debug.apk';shutil.copyfile(apk,target)
    expected=['history-ru.png','login-ru.png','login-uz.png','subscriptions-ru.png','visits-ru.png','visits-uz.png']
    for name in expected:
        require((OUT/'screenshots'/name).is_file(),'native_screenshot_missing')
    require(sorted(p.name for p in (OUT/'screenshots').glob('*.png'))==expected,'native_screenshot_set_changed')
    source={}
    for path in sorted((ROOT/'android').rglob('*')):
        if not path.is_file() or any(part in ('build','.gradle') for part in path.relative_to(ROOT/'android').parts) or path.name=='local.properties':continue
        if path.suffix in ('.java','.xml','.gradle','.properties','.py','.lockfile','.md','.txt') or path.name=='gradle.lockfile':source[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('ci/android_fixture.py','ci/verify_android.py','backend/kinder/auth.py','backend/kinder/store.py','backend/kinder/api.py'):
        source[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    receipt={'schema':'kinder-native-android-v1','revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'jvm':unit,'fixture_emulator':fixture,'review_emulator':review,'apk_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'apk_bytes':target.stat().st_size,'screenshots':{name:hashlib.sha256((OUT/'screenshots'/name).read_bytes()).hexdigest() for name in expected},
        'source_sha256':source,'min_sdk':26,'target_sdk':36,'gradle':'8.13','agp':'8.13.2','test_data_only':True,
        'review_api_origin':'https://example.invalid','review_cleartext_allowed':False,'review_flag_secure':True,
        'fixture_http_host':'10.0.2.2:18763','production_connected':False,'owner_release_signed':False,'published':False}
    (OUT/'native-report.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print('android_native_apk_16_jvm_10_fixture_1_review_tests_and_six_screenshots=PASS')
except Exception as exc:
    (OUT/'native-gate-failure.json').write_text(json.dumps({'status':'failed','error_type':type(exc).__name__,'published':False})+'\n')
    print('native_acceptance=FAILED:'+type(exc).__name__);raise SystemExit(1)
