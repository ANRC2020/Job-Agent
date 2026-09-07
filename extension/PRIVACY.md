# Browser Companion Privacy

Clover Browser Companion is local-first. It communicates only with the Clover desktop service on
`127.0.0.1` and does not send page content to a hosted service.

## Data it reads

After a user grants access for the current site, the extension can read visible job-posting text,
basic page metadata, and supported application-field labels, constraints, and current values. It
excludes known sensitive and unsupported field categories before sending page context to Clover.
When the user chooses **Upload resume**, the original active resume file travels only from Clover's
local data folder through the loopback service to the selected page's resume or CV input.

## Data it stores

The extension stores only its local Clover address and a revocable bearer token in Chromium's local
extension storage. It does not store page captures, browsing history, generated answers, or form
values.

Clover also keeps only a hash of the token. One-time pairing codes expire after ten minutes and are
stored as hashes.

## User control

Site access is optional and granted one site at a time from a user gesture. Users can remove site
permissions in Chromium, disconnect locally from the extension, or revoke a connection in Clover
Settings. Passive browsing is not captured. A page is inspected only while the Clover side panel is
being used.

Saving an opportunity is a separate explicit action. Autofill and resume attachment provide an Undo
action during the current page session and never submit by themselves. Final submission is a
separate one-time approval bound to the reviewed page; Clover rechecks required fields immediately
before clicking one unambiguous submit control. Because employer sites vary, the user must confirm
the resulting page says the application was received.
