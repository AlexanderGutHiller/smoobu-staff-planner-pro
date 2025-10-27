
def render_admin_dashboard(admin_id: int) -> str:
    return f'''
    <html>
        <head><title>Smoobu Staff Planner</title></head>
        <body>
            <h1>Willkommen, Admin!</h1>
            <a href="/admin/{admin_id}/import">Jetzt importieren</a>
        </body>
    </html>
    '''
