"""Eventos APSo, etapa 1. Alvo fixo; nenhuma operação bancária ou edição de eventos."""
import os
import re
from urllib.parse import urlparse

URL = "https://eventosapso.com/system/lista_admin_pagtos.php"


class NeedsReview(Exception):
    pass


def prepare_list(page):
    selects = page.locator("select").all()
    candidates = []
    for select in selects:
        option = select.locator("option").filter(has_text=re.compile(r"^\s*Todos\s*$", re.I))
        if option.count() == 1:
            candidates.append((select, option.first.get_attribute("value")))
    named = [c for c in candidates if "situa" in ((c[0].get_attribute("name") or "") + (c[0].get_attribute("id") or "")).lower()]
    candidates = named or candidates
    if len(candidates) != 1:
        raise NeedsReview("Não identifiquei com segurança Situação: Todos. Precisamos conferir esse campo no portal.")
    select, value = candidates[0]
    form = select.locator("xpath=ancestor::form[1]")
    scope = form if form.count() == 1 else page
    button = scope.get_by_role("button", name=re.compile(r"^\s*Filtrar\s*$", re.I))
    if button.count() != 1:
        raise NeedsReview("Não identifiquei um único botão Filtrar. Precisamos ajustar esse passo.")
    select.select_option(value=value)
    with page.expect_response(lambda r: urlparse(r.url).hostname == 'eventosapso.com' and r.request.resource_type in ('document', 'xhr', 'fetch'), timeout=20000) as response:
        button.click()
    if response.value.status >= 400:
        raise NeedsReview('O portal não confirmou o filtro. Confira a disponibilidade da lista.')
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(300)
    header = page.get_by_role("columnheader", name=re.compile(r"^\s*Encerra em\s*$", re.I))
    header.wait_for(state="visible", timeout=20000)
    if header.count() != 1:
        raise NeedsReview("Há mais de uma coluna Encerra em. Precisamos identificar a tabela correta.")
    table = header.locator("xpath=ancestor::table[1]")
    # Wait for AJAX tables to finish before checking ordering.
    page.wait_for_function("() => ![...document.querySelectorAll('.dataTables_processing,.dt-processing')].some(e=>e.offsetParent!==null)")
    if page.locator("select").evaluate_all("els => !els.some(s=>[...s.options].some(o=>/^\\s*Todos\\s*$/i.test(o.textContent)&&o.selected))"):
        raise NeedsReview("O portal não manteve Situação Todos após o filtro.")
    rows = table.locator("tbody tr")
    if rows.count() == 0 or (rows.count() == 1 and re.search(r"nenhum|sem registros|no data|no matching|não há", rows.first.inner_text(), re.I)):
        return {"visibleCount": 0, "message": "Filtro aplicado. Nenhum evento foi encontrado na lista.", "events": []}, table
    check = """h => {
      if(h.getAttribute('aria-sort')) return h.getAttribute('aria-sort')==='descending';
      if(/(^|\\s)(sorting_desc|dt-ordering-desc)(\\s|$)/.test(h.className)) return true;
      if(/(^|\\s)(sorting_asc|dt-ordering-asc)(\\s|$)/.test(h.className)) return false;
      const i=[...h.parentElement.children].indexOf(h),t=h.closest('table');
      const d=[...t.querySelectorAll('tbody tr')].map(r=>r.children[i]?.textContent.match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})/)).filter(Boolean).map(m=>Number(m[3]+m[2]+m[1]));
      return d.length>1&&new Set(d).size>1&&d.every((v,i)=>!i||d[i-1]>=v);
    }"""
    for _ in range(3):
        if header.evaluate(check):
            break
        header.click()
        page.wait_for_function("h => h.getAttribute('aria-sort')==='descending'||h.getAttribute('aria-sort')==='ascending'||/sorting_|dt-ordering-/.test(h.className)", arg=header.element_handle(), timeout=2000) if header.get_attribute("aria-sort") else page.wait_for_timeout(700)
    if not header.evaluate(check):
        raise NeedsReview("Não consegui confirmar Encerra em do mais recente para o mais antigo. Precisamos conferir os elementos da coluna.")
    events = table.evaluate("t=>[...t.querySelectorAll('tbody tr')].slice(0,2000).map(r=>[...r.cells].slice(0,12).map(c=>c.innerText.slice(0,300)))")
    headers = table.locator('thead tr').last.locator('th,td').all_text_contents()
    return {"visibleCount": len(events), "message": "Situação Todos, filtro aplicado e eventos ordenados por encerramento recente.", "events": events, "headers": headers}, table


def run_portal(image_path):
    from playwright.sync_api import sync_playwright
    username, password = os.getenv("EVENTOS_USERNAME"), os.getenv("EVENTOS_PASSWORD")
    if not username or not password:
        raise NeedsReview("O acesso ao Eventos APSo ainda precisa ser configurado no servidor.")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=False)
            # Only the known portal can navigate the main frame. No arbitrary URL is accepted from API callers.
            def guard(route):
                req = route.request
                if req.is_navigation_request() and req.frame == page.main_frame and urlparse(req.url).hostname != "eventosapso.com":
                    route.abort()
                else:
                    route.continue_()
            page = context.new_page()
            page.set_default_timeout(20000)
            page.route("**/*", guard)
            page.goto(URL, wait_until="domcontentloaded")
            if page.locator('input[type="password"]').count():
                user = page.get_by_label(re.compile(r"^Login$", re.I))
                if user.count() != 1:
                    user = page.locator('input[name="login"],input[name="username"],input[type="text"]')
                pwd = page.locator('input[type="password"]')
                if user.count() != 1 or pwd.count() != 1:
                    raise NeedsReview("Os campos de login precisam ser identificados antes de continuar.")
                user.fill(username)
                pwd.fill(password)
                page.get_by_role("button", name=re.compile(r"^\s*Entrar\s*$", re.I)).click()
                page.wait_for_load_state("domcontentloaded")
                # Do not capture a login screen or return authentication details.
                if page.locator('input[type="password"]').count():
                    raise NeedsReview("O portal não confirmou o login. Confira o acesso e possíveis códigos ou verificações.")
                page.goto(URL, wait_until="domcontentloaded")
            if urlparse(page.url).hostname != "eventosapso.com" or "login" in urlparse(page.url).path:
                raise NeedsReview("O portal pede uma nova autenticação. Confira o acesso no servidor.")
            result, table = prepare_list(page)
            table.screenshot(path=str(image_path))
            return result
        finally:
            browser.close()
