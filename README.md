# TCL TV-bevakare — Kom igång (ingen kod, bara klick)

Total tid: ~5 minuter. Du kommer aldrig att öppna eller redigera en kodfil.
Ingen notis skickas någonstans — allt visas på sidan du öppnar.

## Steg 1 — Skapa GitHub-konto och repo
1. Gå till github.com och skapa ett gratiskonto om du inte har ett.
2. Klicka **"New repository"**. Ge det ett namn, t.ex. `tv-bevakare`. Välj **Public** (krävs för gratis GitHub Pages). Klicka **Create repository**.
3. På reposidan: klicka **"Add file" → "Upload files"**.
4. Packa upp zip-filen du fick, och dra in **alla filer och mappar** (inklusive hela `.github`-mappen med undermappar) i uppladdningsrutan. Klicka **Commit changes**.

## Steg 2 — Sätt igång automatiken
1. Gå till fliken **Actions** högst upp. Om GitHub frågar, klicka **"I understand my workflows, go ahead and enable them"**.
2. Klicka på **"Check TV prices"** i listan till vänster, sedan **"Run workflow"** (grön knapp) → **Run workflow** igen för att bekräfta. Detta kör din första prischeck direkt istället för att vänta på schemat.
3. Vänta ett par minuter tills den gröna bocken dyker upp.

## Steg 3 — Aktivera din sida
1. **Settings → Pages**.
2. Under "Build and deployment": Source = **Deploy from a branch**, Branch = **main**, mapp = **/ (root)**. Klicka **Save**.
3. Efter ~1 minut visas din länk högst upp, typ:
   `https://dittanvändarnamn.github.io/tv-bevakare/`
4. Öppna den, lägg till som bokmärke eller på hemskärmen i mobilen — det är din enda länk från och med nu.

## Vad sidan visar
- Alla TCL-modeller 55–65″ mellan 5 000–10 000 kr från Prisjakt och PriceRunner.
- Aktuellt pris, historiskt lägsta pris, och hur mycket priset sjönk sen förra kollen.
- Uppdateras automatiskt var 2:a timme — bara att öppna sidan och kolla.

## Om något inte fungerar
De medskickade CSS-selektorerna i `scraper.py` är platshållare (se kommentarerna högst upp i filen) — sajternas verkliga HTML-struktur kan skilja sig. Om Actions-körningen misslyckas eller inga kort dyker upp: säg till mig i chatten så hjälper jag dig läsa av felloggen (Actions-fliken → klicka på den röda körningen → läs texten) och justerar filen åt dig, utan att du behöver skriva någon kod själv.
