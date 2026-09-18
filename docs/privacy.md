---
description: What Google Analytics records when you read the Sprout site, what is switched off, how to turn it off, and what it never sees. In English and Spanish.
---

# Privacy: what this site measures

The pages of sprout.chelseakr.com, the live reference and this handbook, use Google Analytics 4
to count visits. Its advertising features are off, and it does not load at all if your browser
asks not to be tracked. The reasoning is in
[ADR 0023](adr/0023-google-analytics-4-on-the-published-site.md).

## What Google Analytics records

When a page loads, Google Analytics records a page view: the page's address, the site you came
from, your browser, device type and screen size, and an approximate location. Google derives that
location from your IP address and says it does not store the address itself. It also records some
interactions Google turns on by default, such as scrolling to the end of a page and following a
link to another site.

The address it receives is cut down first: everything after the page's path is removed before
anything is sent, except campaign tags (`utm_` parameters). A site you arrived from is sent as that
site's address only.

It sets two first-party cookies, `_ga` and `_ga_…`, which let it tell a returning browser from a
new one. They last up to two years. Google LLC receives and stores the data, and this project
keeps it for 14 months.

## What it never sees

**A question you type into the reference.** The deterministic pipeline answers in your browser
tab. The question is never part of a page address, never sent to this project, and never sent to
Google. The same is true of the answer, its citations, and the language you choose.

The corpus files the reference loads (`data/index.json`, `data/config.json`) carry no script, so
nothing that fetches them is counted.

## What is switched off

Google signals and ad personalization are off, and the advertising consent settings are denied for
every reader. Nothing collected here is used to show you ads, joined to a Google account, or sold.
This project has no ad account and no other analytics tool.

## Readers in Europe, the UK and Switzerland

If you are in the European Economic Area, the United Kingdom or Switzerland, analytics storage
defaults to denied. Google Analytics sets no cookie for you, but it still sends Google a cookieless
ping for each page view, without an identifier that links one visit to the next.

## How to turn it off

Google Analytics does not load at all if your browser sends Global Privacy Control or Do Not Track.
You can also use the **Opt out of analytics** button in the footer of the site's pages. It stores
`sprout:analytics-opt-out` in this browser's local storage, not in a cookie, and every page checks
it before loading anything from Google. It covers this browser on this device only, clearing the
site's data clears it, and it does not delete Google cookies already set. The same button reads
**Opt back in** once you have opted out.

## Hosting

The site is static files served by GitHub Pages. GitHub receives each request for a page, as any
web host does, and its handling of that is covered by the
[GitHub General Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).
This project sees no server log and has no accounts or sign-in. The handbook pages also load
their typefaces from Google Fonts, which receives your IP address and browser details when they
load; the live reference page does not.

## En español

Las páginas de sprout.chelseakr.com, la referencia en vivo y este manual, usan Google Analytics 4
para contar visitas. Sus funciones publicitarias están desactivadas y no se carga en absoluto si su
navegador pide que no se le rastree.

**Qué registra.** Cuando se carga una página, registra una vista de página: la dirección de la
página, el sitio del que llegó, su navegador, el tipo de dispositivo y el tamaño de pantalla, y una
ubicación aproximada. Google obtiene esa ubicación a partir de su dirección IP y afirma que no guarda
la dirección en sí. También registra algunas interacciones que Google activa por defecto, como
desplazarse hasta el final de una página o seguir un enlace a otro sitio. La dirección que recibe se
recorta antes: todo lo que sigue a la ruta de la página se elimina, salvo las etiquetas de campaña
(parámetros `utm_`). Del sitio desde el que llegó solo se envía su dirección principal. Crea dos
cookies propias, `_ga` y `_ga_…`, que duran hasta dos años. Google LLC recibe y almacena los datos,
y este proyecto los conserva durante 14 meses.

**Qué no ve nunca.** Una pregunta que escriba en la referencia. La canalización determinista
responde en la pestaña de su navegador; la pregunta nunca forma parte de una dirección, nunca se
envía a este proyecto y nunca se envía a Google. Lo mismo vale para la respuesta, sus citas y el
idioma que elija.

**Qué está desactivado.** Las señales de Google y la personalización de anuncios están
desactivadas, y los permisos de publicidad se deniegan a todos los lectores. Nada de lo que se
recoge aquí se usa para mostrarle anuncios, se vincula a una cuenta de Google ni se vende.

**Europa, el Reino Unido y Suiza.** Si está en el Espacio Económico Europeo, el Reino Unido o Suiza,
el almacenamiento de analítica está denegado por defecto. Google Analytics no le crea ninguna
cookie, pero sigue enviando a Google un aviso sin cookies por cada vista de página, sin un
identificador que relacione una visita con la siguiente.

**Cómo desactivarlo.** Google Analytics no se carga si su navegador envía Global Privacy Control o
Do Not Track. También puede usar el botón **Opt out of analytics** (en inglés: «desactivar la analítica») al
pie de las páginas del sitio. Guarda `sprout:analytics-opt-out` en el almacenamiento local de este
navegador, no en una cookie, y cada página lo comprueba antes de cargar nada de Google. Solo afecta a
este navegador en este dispositivo, se borra al borrar los datos del sitio y no elimina las cookies
de Google ya creadas. Una vez desactivada, el mismo botón permite volver a activarla (**Opt back in**).

**Alojamiento.** El sitio son archivos estáticos servidos por GitHub Pages; este proyecto no ve
registros de servidor y no tiene cuentas ni inicio de sesión. Las páginas del manual también cargan
sus tipos de letra desde Google Fonts, que recibe su dirección IP y datos del navegador al cargarlas;
la página de la referencia en vivo no lo hace.
