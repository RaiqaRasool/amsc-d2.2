import io
import unittest

from result_preview import MAX_PREVIEW_BYTES, preview_export


class ResultPreviewTests(unittest.TestCase):
    def test_rows_columns_and_cells_are_bounded(self):
        data = ('a,b\n' + 'x,y\n' * 1000).encode()
        preview = preview_export(io.BytesIO(data), 'result.csv')
        self.assertEqual(100, len(preview['rows']))
        self.assertTrue(preview['limited'])
        preview = preview_export(io.BytesIO(('h\n' + 'x' * 2000 + '\n').encode()), 'result.csv')
        self.assertEqual(501, len(preview['rows'][0][0]))
        self.assertTrue(preview['limited'])
        wide = ','.join(f'pv{index}' for index in range(100)) + '\n' + ','.join('1' for _ in range(100)) + '\n'
        preview = preview_export(io.BytesIO(wide.encode()), 'result.csv')
        self.assertEqual(50, len(preview['headers']))
        self.assertEqual(50, len(preview['rows'][0]))

    def test_read_budget_is_enforced_for_json_and_csv(self):
        class BoundedSource(io.BytesIO):
            def read(self, size=-1):
                self.requested = size
                if size < 0 or size > MAX_PREVIEW_BYTES + 1:
                    raise AssertionError('Unbounded read')
                return super().read(size)
        for filename in ('result.csv', 'result.json'):
            source = BoundedSource(b'h\n' + b'x' * (MAX_PREVIEW_BYTES * 2))
            preview = preview_export(source, filename)
            self.assertEqual(MAX_PREVIEW_BYTES + 1, source.requested)
            self.assertTrue(preview['limited'])

    def test_csv_quotes_and_partial_records(self):
        data = b'a,b\n"multi\nline","a,b"\n'
        preview = preview_export(io.BytesIO(data), 'result.csv')
        self.assertEqual([['multi\nline', 'a,b']], preview['rows'])
        self.assertFalse(preview['limited'])
        data = b'a,b\n1,2\n"' + b'x' * MAX_PREVIEW_BYTES
        preview = preview_export(io.BytesIO(data), 'result.csv')
        self.assertEqual([['1', '2']], preview['rows'])
        self.assertTrue(preview['limited'])
