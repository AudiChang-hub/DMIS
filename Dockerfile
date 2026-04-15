FROM odoo:16

USER root
RUN pip3 install --no-cache-dir "PyMuPDF==1.23.26" openpyxl
USER odoo
