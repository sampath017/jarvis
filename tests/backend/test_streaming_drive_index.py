import pytest
from src.services import drive_index as service


class Collection:
    def __init__(self):
        self.rows = {}
        self.max_batch = 0
    def matches(self, metadata, where):
        if '$and' in where:
            return all(self.matches(metadata, part) for part in where['$and'])
        return all(metadata.get(key) != value['$ne'] if isinstance(value, dict) else metadata.get(key) == value
            for key, value in where.items())
    def get(self, where, include=None, limit=100, offset=0):
        found = [(id, value) for id, value in self.rows.items() if self.matches(value, where)][offset:offset + limit]
        return {'ids': [item[0] for item in found], 'metadatas': [item[1] for item in found]}
    def upsert(self, ids, embeddings, documents, metadatas):
        self.max_batch = max(self.max_batch, len(ids))
        assert all(len(id) <= 128 for id in ids)
        for id, metadata in zip(ids, metadatas):
            self.rows[id] = metadata
    def update(self, ids, metadatas):
        for id, metadata in zip(ids, metadatas):
            self.rows[id] = metadata
    def delete(self, where):
        for id in list(self.rows):
            if self.matches(self.rows[id], where):
                del self.rows[id]


def test_large_source_has_no_file_or_chunk_cap_and_uses_small_batches(monkeypatch, tmp_path):
    source = tmp_path / 'large.txt'
    with source.open('wb') as stream:
        for _ in range(22):
            stream.write(b'a' * 1024 * 1024)
    coll = Collection()
    monkeypatch.setattr(service, 'index', lambda: coll)
    monkeypatch.setattr(service, 'embed', lambda items: [[0.] * 768 for _ in items])
    memory = {'account': 'a', 'id': 'f', 'name': 'Test', 'mimeType': 'text/plain',
        'url': 'https://drive.google.com/file/d/f', 'source_version': '42'}
    result = service.put_file('owner', memory, source)
    assert result['chunks'] > 500
    assert len(coll.rows) == result['chunks']
    assert coll.max_batch <= 2
    assert all(row['complete'] for row in coll.rows.values())
    memory['source_version'] = '43'
    memory['name'] = 'Renamed Test'
    monkeypatch.setattr(service, 'embed', lambda items: pytest.fail('Unchanged content must reuse embeddings'))
    refreshed = service.put_file('owner', memory, source)
    assert refreshed == {'status': 'unchanged', 'chunks': result['chunks'], 'coverage': 'content', 'issues': {}, 'reader_version': 2}
    assert all(row['source_version'] == '43' and row['name'] == 'Renamed Test' for row in coll.rows.values())


def test_pdf_beyond_200_pages_is_processed(tmp_path):
    import pymupdf
    source = tmp_path / 'long.pdf'
    with pymupdf.open() as document:
        for _ in range(201):
            page = document.new_page()
            page.insert_text((30, 30), 'Readable page content. ' * 8)
        document.save(source)
    units = list(service.chunks(source, 'application/pdf', 'Long PDF'))
    assert len(units) == 201
    assert units[-1][2].startswith('page 201')
