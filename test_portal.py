"""Browser fixture tests; no login or connection to the real portal."""
import os
import re
import unittest
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
from portal import prepare_list, NeedsReview, URL


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.p = sync_playwright().start()
        options = {'headless': True}
        if os.getenv('ROBOT_TEST_BROWSER'):
            options['executable_path'] = os.environ['ROBOT_TEST_BROWSER']
        self.browser = self.p.chromium.launch(**options)
        self.page = self.browser.new_page()
        self.empty = False
        self.ambiguous = False
        self.page.route('**/*', self.fixture)

    def tearDown(self):
        self.browser.close()
        self.p.stop()

    def fixture(self, route):
        selected = parse_qs(urlparse(route.request.url).query).get('situacao') == ['todos']
        opts = '<option value="abertos">Abertos</option><option value="todos" '+('selected' if selected else '')+'>Todos</option>'
        rows = '<tr><td colspan="2">Nenhum registro encontrado</td></tr>' if self.empty else '<tr><td>Antigo</td><td>01/08/2026</td></tr><tr><td>Recente</td><td>31/10/2026</td></tr>'
        select = '<select id="situacao" name="situacao">'+opts+'</select>' if not self.ambiguous else '<select>'+opts+'</select><select>'+opts+'</select>'
        html = '<form><label for="situacao">Situação</label>'+select+'<button type="submit">Filtrar</button></form><table><thead><tr><th>Nome</th><th aria-sort="ascending" onclick="this.setAttribute(\'aria-sort\',this.getAttribute(\'aria-sort\')===\'descending\'?\'ascending\':\'descending\');let b=document.querySelector(\'tbody\');[...b.rows].reverse().forEach(r=>b.append(r));">Encerra em</th></tr></thead><tbody>'+rows+'</tbody></table>'
        route.fulfill(content_type='text/html', body=html)

    def test_filters_reloads_sorts_and_returns_visible_rows(self):
        self.page.goto(URL)
        result, _ = prepare_list(self.page)
        self.assertEqual(parse_qs(urlparse(self.page.url).query)['situacao'], ['todos'])
        self.assertEqual(result['visibleCount'], 2)
        self.assertEqual(result['events'][0], ['Recente', '31/10/2026'])
        self.assertEqual(result['headers'], ['Nome', 'Encerra em'])

    def test_empty_is_a_valid_result(self):
        self.empty = True
        self.page.goto(URL)
        result, _ = prepare_list(self.page)
        self.assertEqual(result['visibleCount'], 0)
        self.assertEqual(result['events'], [])

    def test_ambiguous_fields_stop_before_clicking(self):
        self.ambiguous = True
        self.page.goto(URL)
        with self.assertRaises(NeedsReview):
            prepare_list(self.page)
        self.assertEqual(urlparse(self.page.url).query, '')


if __name__ == '__main__':
    unittest.main()
