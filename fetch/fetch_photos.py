"""Free-licensed photos used on the site (Wikimedia Commons, CC BY 4.0).

Only photos of places (bus stops), never of pantry clients. Credits are shown
on the page next to each photo and in sources.toml.
"""
from common import download

PHOTOS = {
    "aero-peoria-11th.jpg": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/Aero_bus_stop_7015_S_Peoria_Ave_and_11th_St_Tulsa_OK_2025-07-21_10-08-39.jpg/1280px-Aero_bus_stop_7015_S_Peoria_Ave_and_11th_St_Tulsa_OK_2025-07-21_10-08-39.jpg",
    "aero-stop-8005.jpg": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/31/Tulsa_Transit_Aero_bus_stop_8005_OK_2025-03-16_16-05-20_1.jpg/1280px-Tulsa_Transit_Aero_bus_stop_8005_OK_2025-03-16_16-05-20_1.jpg",
}
for name, url in PHOTOS.items():
    download("photos", name, url, extra={"license": "CC BY 4.0", "author": "G. Edward Johnson",
                                         "source": "Wikimedia Commons"})
