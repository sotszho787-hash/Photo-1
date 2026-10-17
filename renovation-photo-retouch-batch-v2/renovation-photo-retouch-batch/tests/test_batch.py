import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.batch import perform, extract_zip_safely, load_overrides, sha256_file, validate_options

CFG={
  'faithful_strength':.45,'aesthetic_strength':.82,'default_light':'unknown',
  'max_megapixels':48, 'jpeg_quality':95,'comparison_max_width':600,
  'process_subfolders':True,'max_archive_files':800,'max_archive_uncompressed_mb':4096
}


def photo(path, alpha=False, size=(480,320)):
    path.parent.mkdir(parents=True,exist_ok=True)
    m='RGBA' if alpha else 'RGB'
    im=Image.new(m,size,(213,198,180,255) if alpha else (213,198,180))
    d=ImageDraw.Draw(im)
    d.rectangle((40,20,190,290),fill=(143,116,80,255) if alpha else (143,116,80))
    d.rectangle((300,40,430,190),fill=(243,240,234,255) if alpha else (243,240,234))
    im.save(path)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.home=Path(self.t.name)
        self.inp=self.home/'INPUT'
        self.out=self.home/'OUTPUT'
        self.inp.mkdir()

    def tearDown(self):
        self.t.cleanup()

    def test_two_variants_compare_reports_zip_and_source_hash(self):
        good=self.inp/'屯門'/'客廳.jpg'
        other=self.inp/'天水圍'/'浴室.png'
        photo(good); photo(other,alpha=True)
        expected={f:sha256_file(f) for f in (good,other)}
        run,archive,summary=perform(self.inp,self.out,CFG,{})
        self.assertEqual((summary['successful'],summary['failed']),(2,0))
        self.assertEqual(len(list((run/'Faithful').glob('*'))),2)
        self.assertEqual(len(list((run/'Aesthetic').glob('*'))),2)
        self.assertEqual(len(list((run/'Reports'/'Faithful').glob('*'))),2)
        for f,h in expected.items(): self.assertEqual(sha256_file(f),h)
        for f in (run/'Aesthetic').iterdir():
            with Image.open(f) as im:self.assertEqual(im.size,(480,320))
        out_png=next((run/'Faithful').glob('*.png'))
        with Image.open(out_png) as im:self.assertEqual(im.getpixel((0,0))[3],255)
        with zipfile.ZipFile(archive) as z:
            names=z.namelist()
            self.assertEqual(sum(x.startswith('Before_After/') for x in names),4)
            self.assertEqual(sum(x.startswith('Reports/') for x in names),4)
            self.assertIn('Batch_Report.csv',names)
            self.assertIn('Batch_Report.json',names)
        run2,archive2,_=perform(self.inp,self.out,CFG,{})
        self.assertNotEqual(run2,run)
        self.assertNotEqual(archive2,archive)

    def test_bad_photo_does_not_stop(self):
        photo(self.inp/'valid.jpg')
        (self.inp/'bad.jpg').write_bytes(b'not an image')
        run,archive,summary=perform(self.inp,self.out,CFG,{})
        self.assertEqual((summary['successful'],summary['failed']),(1,1))
        self.assertEqual(len(list((run/'Faithful').glob('*.jpg'))),1)
        self.assertTrue(archive.is_file())

    def test_zip_batch_and_traversal_rejection(self):
        photo(self.inp/'廚房.jpg')
        src=self.home/'photos.zip'
        with zipfile.ZipFile(src,'w') as z:z.write(self.inp/'廚房.jpg','site/廚房.jpg')
        run,archive,summary=perform(src,self.out,CFG,{})
        self.assertEqual(summary['successful'],1)
        evil=self.home/'evil.zip'
        with zipfile.ZipFile(evil,'w') as z:z.writestr('../escape.jpg',b'X')
        with self.assertRaises(ValueError):
            perform(evil,self.out,CFG,{})
        self.assertFalse((self.home/'escape.jpg').exists())
        self.assertTrue(archive.is_file())

    def test_failed_second_variant_rolls_back_incomplete_photo(self):
        from unittest import mock
        from app import batch as batch_module
        photo(self.inp/'ok.jpg')
        photo(self.inp/'fail.jpg')
        true_process = batch_module.process

        def flaky_process(src, dest, compare, report, cfg, light, side, sha):
            if src.name == 'fail.jpg' and 'Aesthetic' in str(dest):
                raise RuntimeError('intentional aesthetic failure')
            return true_process(src, dest, compare, report, cfg, light, side, sha)

        with mock.patch.object(batch_module, 'process', side_effect=flaky_process):
            run, archive, summary = perform(self.inp, self.out, CFG, {})
        self.assertEqual((summary['successful'], summary['failed']), (1,1))
        self.assertEqual(len(list((run/'Faithful').glob('*.jpg'))), 1)
        self.assertEqual(len(list((run/'Aesthetic').glob('*.jpg'))), 1)
        self.assertTrue(archive.exists())

    def test_same_basename_in_subfolders(self):
        photo(self.inp/'SiteA'/'IMG_01.jpg')
        photo(self.inp/'SiteB'/'IMG_01.jpg')
        run,archive,summary=perform(self.inp,self.out,CFG,{})
        self.assertEqual(summary['successful'],2)
        self.assertEqual(len(set(p.name for p in (run/'Faithful').iterdir())),2)

    def test_install_codex_skill_backups_existing(self):
        from install_codex_skill import install
        target=self.home/'.agents'/'skills'/'renovation-photo-retouch'
        target.mkdir(parents=True)
        (target/'my_notes.txt').write_text('original personal notes',encoding='utf-8')
        actual=install(self.home)
        self.assertEqual(actual,target)
        self.assertTrue((target/'SKILL.md').exists())
        self.assertTrue((target/'BATCH_PACKAGE_LOCATION.md').exists())
        backups=list(target.parent.glob('renovation-photo-retouch_backup_*'))
        self.assertEqual(len(backups),1)
        self.assertEqual((backups[0]/'my_notes.txt').read_text(encoding='utf-8'),'original personal notes')

    def test_window_override_safeguard(self):
        photo(self.inp/'房間.png')
        rules=self.home/'overrides.csv'
        rules.write_text('filename,light,window_side\n房間.png,window,right\n',encoding='utf-8')
        run,archive,summary=perform(self.inp,self.out,CFG,load_overrides(rules))
        qa=json.loads(next((run/'Reports'/'Aesthetic').iterdir()).read_text(encoding='utf-8'))
        self.assertEqual(qa['confirmed_window_side'],'right')
        self.assertEqual(qa['light_mode'],'window')
        self.assertEqual(qa['strength'],.82)
        rules.write_text('filename,light,window_side\n房間.png,unknown,right\n',encoding='utf-8')
        with self.assertRaises(ValueError):load_overrides(rules)

    def test_output_inside_input_fails(self):
        photo(self.inp/'test.jpg')
        with self.assertRaises(ValueError):perform(self.inp,self.inp/'OUTPUT',CFG,{})

    def test_rgba_alpha_bitwise_unchanged(self):
        img=Image.new('RGBA',(14,11),(40,130,240,0))
        img.putpixel((5,8),(200,50,30,128))
        img.save(self.inp/'transparent.png')
        run,archive,summary=perform(self.inp,self.out,CFG,{})
        with Image.open(next((run/'Faithful').glob('*.png'))) as im:
            self.assertTrue(np.array_equal(np.array(im.getchannel('A')),np.array(img.getchannel('A'))))

if __name__=='__main__':unittest.main()
