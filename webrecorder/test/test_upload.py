from .testutils import FullStackTests

import os
import webtest
import json
import time

from webrecorder.models.stats import Stats
from webrecorder.models.base import RedisUniqueComponent
from webrecorder.utils import today_str

from webrecorder.models.usermanager import CLIUserManager
from warcio import ArchiveIterator


# ============================================================================
class TestUpload(FullStackTests):
    ID_1 = '1884e17293'
    ID_2 = 'eed99fa580'
    ID_3 = 'fc17891a4a'

    timestamps = dict(created_at={},
                      updated_at={},
                      recorded_at={}
                     )

    @classmethod
    def setup_class(cls, **kwargs):
        super(TestUpload, cls).setup_class(temp_worker=False)

        cls.manager = CLIUserManager()

        cls.warc = None

        cls.test_upload_warc = os.path.join(cls.get_curr_dir(), 'warcs', 'test_3_15_upload.warc.gz')

    def test_upload_anon(self):
        with open(self.test_upload_warc, 'rb') as fh:
            res = self.testapp.put('/_upload?filename=example2.warc.gz', params=fh.read(), status=400)

        assert res.json == {'error': 'not_logged_in'}

    def test_create_user_def_coll(self):
        self.manager.create_user('test@example.com', 'test', 'TestTest123', 'archivist', 'Test')

    def test_login(self):
        params = {'username': 'test',
                  'password': 'TestTest123',
                 }

        res = self.testapp.post_json('/api/v1/auth/login', params=params)

        assert res.json == {'anon': False,
                            'coll_count': 1,
                            'role': 'archivist',
                            'username': 'test',
                           }

        assert self.testapp.cookies.get('__test_sesh', '') != ''

    def test_default_coll(self):
        res = self.testapp.get('/test/default-collection')
        res.charset = 'utf-8'
        assert '"test"' in res.text

    def test_logged_in_record_1(self):
        self.set_uuids('Recording', ['rec-sesh'])
        res = self.testapp.get('/_new/default-collection/rec-sesh/record/mp_/http://httpbin.org/get?food=bar')
        assert res.headers['Location'].endswith('/test/default-collection/rec-sesh/record/mp_/http://httpbin.org/get?food=bar')
        res = res.follow()
        res.charset = 'utf-8'

        assert '"food": "bar"' in res.text, res.text

        assert self.testapp.cookies['__test_sesh'] != ''

        # Add as page
        page = {'title': 'Example Title', 'url': 'http://httpbin.org/get?food=bar', 'timestamp': '2016010203000000'}
        res = self.testapp.post_json('/api/v1/recording/rec-sesh/pages?user=test&coll=default-collection', params=page)

        assert res.json['page_id']
        page_id = res.json['page_id']

        # Add list
        params = {'title': 'New List',
                  'desc': 'List Description Goes Here!'
                 }

        res = self.testapp.post_json('/api/v1/lists?user=test&coll=default-collection', params=params)

        blist = res.json['list']
        list_id = blist['id']

        # Add bookmark
        page['page_id'] = page_id
        res = self.testapp.post_json('/api/v1/list/%s/bookmarks?user=test&coll=default-collection' % list_id, params=page)

        bookmark = res.json['bookmark']

    def test_logged_in_record_2(self):
        self.set_uuids('Recording', ['another-sesh'])
        res = self.testapp.get('/_new/default-collection/another-sesh/record/mp_/http://httpbin.org/get?bood=far')
        assert res.headers['Location'].endswith('/test/default-collection/another-sesh/record/mp_/http://httpbin.org/get?bood=far')
        res = res.follow()
        res.charset = 'utf-8'

        assert '"bood": "far"' in res.text, res.text

        assert self.testapp.cookies['__test_sesh'] != ''

        # Add as page
        page = {'title': 'Example Title 2', 'url': 'http://httpbin.org/get?bood=far', 'timestamp': '2016010203000000'}
        res = self.testapp.post_json('/api/v1/recording/another-sesh/pages?user=test&coll=default-collection', params=page)

        assert res.json['page_id']
        page_id = res.json['page_id']

        # Add list
        params = {'title': 'New List 2',
                  'desc': 'Another List'
                 }

        res = self.testapp.post_json('/api/v1/lists?user=test&coll=default-collection', params=params)

        blist = res.json['list']
        list_id = blist['id']

        # Add bookmark
        page['page_id'] = page_id
        res = self.testapp.post_json('/api/v1/list/%s/bookmarks?user=test&coll=default-collection' % list_id, params=page)

        bookmark = res.json['bookmark']

    def test_logged_in_download_coll(self):
        res = self.testapp.get('/test/default-collection/$download')

        assert res.headers['Content-Disposition'].startswith("attachment; filename*=UTF-8''default-collection-")

        TestUpload.warc = self._get_dechunked(res.body)

    def test_read_warcinfo(self):
        self.warc.seek(0)
        metadata = []

        for record in ArchiveIterator(self.warc):
            if record.rec_type == 'warcinfo':
                stream = record.content_stream()
                warcinfo = {}

                while True:
                    line = stream.readline().decode('utf-8')
                    if not line:
                        break

                    parts = line.split(': ', 1)
                    warcinfo[parts[0].strip()] = parts[1].strip()

                assert set(warcinfo.keys()) == {'software', 'format', 'creator', 'isPartOf', 'json-metadata'}
                assert warcinfo['software'].startswith('Webrecorder Platform ')
                assert warcinfo['format'] == 'WARC File Format 1.0'
                assert warcinfo['creator'] == 'test'
                assert warcinfo['isPartOf'] in ('default-collection', 'default-collection/rec-sesh', 'default-collection/another-sesh')

                metadata.append(json.loads(warcinfo['json-metadata']))

        assert len(metadata) == 3
        assert metadata[0]['type'] == 'collection'
        assert set(metadata[0].keys()) == {'created_at', 'updated_at',
                                           'title', 'desc', 'type', 'size',
                                           'lists', 'public', 'public_index'}

        assert metadata[0]['title'] == 'Default Collection'
        assert 'This is your first' in metadata[0]['desc']

        assert metadata[1]['type'] == 'recording'
        assert set(metadata[1].keys()) == {'created_at', 'updated_at', 'recorded_at',
                                           'title', 'desc', 'type', 'size',
                                           'pages'}

        assert metadata[0]['created_at'] <= metadata[0]['updated_at']

        for metadata_item in metadata:
            for field in TestUpload.timestamps.keys():
                if field == 'recorded_at' and metadata_item['type'] == 'collection':
                    continue

                TestUpload.timestamps[field][metadata_item['title']] = RedisUniqueComponent.to_iso_date(metadata_item[field])

        assert set(TestUpload.timestamps['created_at'].keys()) == {'rec-sesh', 'another-sesh', 'Default Collection'}

    def test_upload_error_out_of_space(self):
        max_size = self.redis.hget('u:test:info', 'max_size')
        self.redis.hset('u:test:info', 'max_size', '5')

        res = self.testapp.put('/_upload?filename=example.warc.gz', params=self.warc.getvalue(), status=400)

        assert res.json == {'error': 'out_of_space'}
        self.redis.hset('u:test:info', 'max_size', max_size)

    def test_logged_in_upload_coll(self):
        time.sleep(1.0)

        res = self.testapp.put('/_upload?filename=example.warc.gz', params=self.warc.getvalue())
        res.charset = 'utf-8'
        assert res.json['user'] == 'test'
        assert res.json['upload_id'] != ''

        upload_id = res.json['upload_id']

        res = self.testapp.get('/_upload/' + upload_id + '?user=test')

        assert res.json['coll'] == 'default-collection-2'
        assert res.json['coll_title'] == 'Default Collection'
        assert res.json['filename'] == 'example.warc.gz'
        assert res.json['files'] == 1
        assert res.json['total_size'] >= 3000
        assert res.json['done'] == False

        def assert_finished():
            res = self.testapp.get('/_upload/' + upload_id + '?user=test')
            assert res.json['done'] == True
            assert res.json['size'] >= res.json['total_size']

        self.sleep_try(0.2, 10.0, assert_finished)

    def test_logged_in_replay(self):
        res = self.testapp.get('/test/default-collection-2/mp_/http://httpbin.org/get?food=bar')
        res.charset = 'utf-8'

        assert '"food": "bar"' in res.text, res.text

    def test_uploaded_coll_info(self):
        res = self.testapp.get('/api/v1/collection/default-collection-2?user=test')

        assert res.json['collection']
        collection = res.json['collection']

        assert 'This is your first collection' in collection['desc']
        assert collection['id'] == 'default-collection-2'
        assert collection['title'] == 'Default Collection'
        assert collection['slug'] == 'default-collection-2'

        for field in TestUpload.timestamps.keys():
            if field == 'recorded_at':
                continue

            assert TestUpload.timestamps[field][collection['title']] == collection[field], (field, collection.get('title'))

        for recording in collection['recordings']:
            for field in TestUpload.timestamps.keys():
                assert TestUpload.timestamps[field][recording['title']] == recording[field], (field, recording.get('title'))

        assert len(collection['lists']) == 2
        assert collection['lists'][0]['desc'] == 'List Description Goes Here!'
        assert collection['lists'][0]['title'] == 'New List'
        assert collection['lists'][0]['slug'] == 'new-list'

        assert collection['lists'][1]['desc'] == 'Another List'
        assert collection['lists'][1]['title'] == 'New List 2'
        assert collection['lists'][1]['slug'] == 'new-list-2'

        # Pages
        assert len(collection['pages']) == 2
        assert len(collection['recordings']) == 2

        # ensure each page maps to a recording
        assert (set([page['rec'] for page in collection['pages']]) ==
                set([recording['id'] for recording in collection['recordings']]))

        # First List
        assert len(collection['lists'][0]['bookmarks']) == 1
        bookmark = collection['lists'][0]['bookmarks'][0]

        assert bookmark['timestamp'] == '2016010203000000'
        assert bookmark['url'] == 'http://httpbin.org/get?food=bar'
        assert bookmark['title'] == 'Example Title'

        assert bookmark['page_id'] in [page['id'] for page in collection['pages']]

        # Second List
        assert len(collection['lists'][1]['bookmarks']) == 1
        bookmark = collection['lists'][1]['bookmarks'][0]

        assert bookmark['timestamp'] == '2016010203000000'
        assert bookmark['url'] == 'http://httpbin.org/get?bood=far'
        assert bookmark['title'] == 'Example Title 2'

        assert bookmark['page_id'] in [page['id'] for page in collection['pages']]

    def test_upload_3_x_warc(self):
        self.set_uuids('Recording', ['uploaded-rec'])
        with open(self.test_upload_warc, 'rb') as fh:
            res = self.testapp.put('/_upload?filename=example2.warc.gz', params=fh.read())

        res.charset = 'utf-8'
        assert res.json['user'] == 'test'
        assert res.json['upload_id'] != ''

        upload_id = res.json['upload_id']
        res = self.testapp.get('/_upload/' + upload_id + '?user=test')

        assert res.json['coll'] == 'temporary-collection'
        assert res.json['coll_title'] == 'Temporary Collection'
        assert res.json['filename'] == 'example2.warc.gz'
        assert res.json['files'] == 1
        assert res.json['total_size'] == 5192
        assert res.json['done'] == False

        def assert_finished():
            res = self.testapp.get('/_upload/' + upload_id + '?user=test')
            assert res.json['done'] == True
            assert res.json['size'] >= res.json['total_size']

        self.sleep_try(0.2, 10.0, assert_finished)

    def test_replay_2(self):
        res = self.testapp.get('/test/temporary-collection/mp_/http://example.com/')
        res.charset = 'utf-8'

        assert 'Example Domain' in res.text, res.text

    def test_uploaded_coll_info_2(self):
        res = self.testapp.get('/api/v1/collection/temporary-collection?user=test')

        assert res.json['collection']
        collection = res.json['collection']

        assert collection['desc'] == ''
        assert collection['id'] == 'temporary-collection'
        assert collection['slug'] == 'temporary-collection'
        assert collection['title'] == 'Temporary Collection'

        assert collection['pages'] == [{'id': self.ID_1,
                                        'rec': 'uploaded-rec',
                                        'timestamp': '20180306181354',
                                        'title': 'Example Domain',
                                        'url': 'http://example.com/'}]

    def test_upload_force_coll(self):
        self.set_uuids('Recording', ['upload-rec-2'])
        with open(self.test_upload_warc, 'rb') as fh:
            res = self.testapp.put('/_upload?filename=example2.warc.gz&force-coll=default-collection', params=fh.read())

        res.charset = 'utf-8'
        assert res.json['user'] == 'test'
        assert res.json['upload_id'] != ''

        upload_id = res.json['upload_id']
        res = self.testapp.get('/_upload/' + upload_id + '?user=test')

        assert res.json['coll'] == 'default-collection'
        assert res.json['coll_title'] == 'Default Collection'
        assert res.json['filename'] == 'example2.warc.gz'
        assert res.json['files'] == 1
        assert res.json['total_size'] >= 3000
        assert res.json['done'] == False

        def assert_finished():
            res = self.testapp.get('/_upload/' + upload_id + '?user=test')
            assert res.json['done'] == True
            assert res.json['size'] >= res.json['total_size']

        self.sleep_try(0.2, 10.0, assert_finished)

    def test_coll_info_replay_3(self):
        res = self.testapp.get('/api/v1/collection/default-collection?user=test')

        assert res.json['collection']
        collection = res.json['collection']

        assert collection['id'] == 'default-collection'
        assert 'This is your first collection' in collection['desc']
        assert collection['title'] == 'Default Collection'

        assert len(collection['pages']) == 3

        print(collection['pages'])

        assert {'id': self.ID_2,
                'rec': 'upload-rec-2',
                'timestamp': '20180306181354',
                'title': 'Example Domain',
                'url': 'http://example.com/'} in collection['pages']

        assert {'id': self.ID_3,
                'rec': 'rec-sesh',
                'timestamp': '2016010203000000',
                'title': 'Example Title',
                'url': 'http://httpbin.org/get?food=bar'} in collection['pages']


    def test_replay_3(self):
        res = self.testapp.get('/test/default-collection/mp_/http://example.com/')
        res.charset = 'utf-8'

        assert 'Example Domain' in res.text, res.text

        res = self.testapp.get('/api/v1/collection/default-collection?user=test')
        assert len(res.json['collection']['recordings']) == 3

    def test_logout_1(self):
        res = self.testapp.get('/api/v1/auth/logout', status=200)
        assert res.json['success']
        assert self.testapp.cookies.get('__test_sesh', '') == ''

    def test_replay_error_logged_out(self):
        res = self.testapp.get('/test/default-collection/mp_/http://example.com/', status=404)

    def test_upload_anon_2(self):
        with open(self.test_upload_warc, 'rb') as fh:
            res = self.testapp.put('/_upload?filename=example2.warc.gz', params=fh.read(), status=400)

        assert res.json == {'error': 'not_logged_in'}

    def test_stats(self):
        assert self.redis.hget(Stats.DOWNLOADS_USER_COUNT_KEY, today_str()) == '1'
        assert self.redis.hget(Stats.UPLOADS_COUNT_KEY, today_str()) == '3'




