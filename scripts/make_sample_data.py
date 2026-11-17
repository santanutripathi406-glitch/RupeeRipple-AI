"""Regenerates data/sample_data.csv (synthetic data for 'Madurai Handloom Traders', a fictional business).
Dates are stored relative to ANCHOR; the app shifts them so day 0 == today."""
import csv, datetime as dt, pathlib

ANCHOR = dt.date(2026, 1, 1)
# id, entity, entity_type, txn_type, amount, due_off, exp_off, status, related, flex
ROWS = [
 ("R001","Kaveri Retail Mart","customer","receivable",480000,7,8,"pending","Warp Yarn Suppliers","fixed"),
 ("R002","Chennai Fashion Hub","customer","receivable",220000,15,17,"pending","","fixed"),
 ("R003","Coimbatore Sarees Co","customer","receivable",150000,22,22,"pending","","fixed"),
 ("R004","Madurai Silks Outlet","customer","receivable",260000,30,33,"pending","","fixed"),
 ("R005","Trichy Garments Co","customer","receivable",180000,40,42,"pending","","fixed"),
 ("R006","Kaveri Retail Mart","customer","receivable",300000,52,52,"pending","","fixed"),
 ("R007","Salem Uniform Supply","customer","receivable",120000,12,12,"pending","","fixed"),
 ("P001","Warp Yarn Suppliers","supplier","payable",190000,10,10,"pending","Kaveri Retail Mart","fixed"),
 ("P002","Dye & Chemicals Ltd","supplier","payable",85000,12,12,"pending","","flexible"),
 ("P003","Packaging Hub","supplier","payable",40000,18,18,"pending","","flexible"),
 ("P004","Weaver Cooperative","supplier","payable",210000,20,20,"pending","","fixed"),
 ("P005","Logistics Partners","supplier","payable",55000,25,25,"pending","","flexible"),
 ("P006","Raw Cotton Mill","supplier","payable",240000,35,35,"pending","","fixed"),
 ("P007","Dye & Chemicals Ltd","supplier","payable",90000,45,45,"pending","","flexible"),
 ("PR001","Staff Payroll - Month 1","employee","payroll",160000,6,6,"pending","","fixed"),
 ("PR002","Staff Payroll - Month 2","employee","payroll",160000,36,36,"pending","","fixed"),
 ("RT001","Factory & Showroom Rent","landlord","rent",75000,5,5,"pending","","fixed"),
 ("RT002","Factory & Showroom Rent","landlord","rent",75000,35,35,"pending","","fixed"),
 ("UT001","State Electricity Board","utility","utilities",28000,14,14,"pending","","fixed"),
 ("UT002","State Electricity Board","utility","utilities",30000,44,44,"pending","","fixed"),
 ("UT003","Broadband Provider","utility","utilities",6000,16,16,"pending","","flexible"),
 ("OT001","Loom Upgrade (planned purchase)","supplier","other",120000,28,28,"pending","","flexible"),
 ("OT002","Marketing Campaign","supplier","other",45000,38,38,"pending","","flexible"),
 ("OT003","GST Payment","government","other",90000,20,20,"pending","","fixed"),
]
def main():
    out = pathlib.Path(__file__).resolve().parents[1] / "data" / "sample_data.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["transaction_id","entity_name","entity_type","transaction_type","amount",
                    "due_date","expected_date","status","related_entity","flexibility"])
        for r in ROWS:
            w.writerow([r[0], r[1], r[2], r[3], r[4], ANCHOR + dt.timedelta(days=r[5]),
                        ANCHOR + dt.timedelta(days=r[6]), r[7], r[8], r[9]])
if __name__ == "__main__":
    main()
