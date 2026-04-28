"""Invoice and client management endpoints."""

import io
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..logger import logger
from ..models import (
    Client,
    ClientCreate,
    ClientResponse,
    ClientUpdate,
    Invoice,
    InvoiceCreate,
    InvoiceItem,
    InvoiceResponse,
    InvoiceStatus,
    InvoiceUpdate,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])


# Client endpoints
@router.get("/clients", response_model=list[ClientResponse])
async def list_clients(
    active_only: bool = Query(True),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List all clients."""
    q = db.query(Client)
    if active_only:
        q = q.filter(Client.is_active == True)  # noqa: E712
    q = q.order_by(Client.name)
    return q.offset(offset).limit(limit).all()


@router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(client_id: int, db: Session = Depends(get_db)):
    """Get a specific client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.post("/clients", response_model=ClientResponse)
async def create_client(client: ClientCreate, db: Session = Depends(get_db)):
    """Create a new client."""
    db_client = Client(**client.model_dump())
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    logger.info(f"Created client: {db_client.name} (ID: {db_client.id})")
    return db_client


@router.put("/clients/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: int, client: ClientUpdate, db: Session = Depends(get_db)
):
    """Update an existing client."""
    db_client = db.query(Client).filter(Client.id == client_id).first()
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")

    update_data = client.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_client, field, value)

    db.commit()
    db.refresh(db_client)
    return db_client


@router.delete("/clients/{client_id}")
async def delete_client(client_id: int, db: Session = Depends(get_db)):
    """Delete a client (soft delete by setting inactive)."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.is_active = False
    db.commit()
    return {"status": "deleted", "id": client_id}


# Invoice endpoints
@router.get("/next-number")
async def get_next_invoice_number(db: Session = Depends(get_db)):
    """Generate the next sequential invoice number (INV-YYYY-NNN)."""
    current_year = datetime.now().year
    prefix = f"INV-{current_year}-"

    # Find the highest number for this year
    latest = (
        db.query(Invoice.invoice_number)
        .filter(Invoice.invoice_number.like(f"{prefix}%"))
        .order_by(Invoice.invoice_number.desc())
        .first()
    )

    if latest:
        try:
            last_num = int(latest[0].replace(prefix, ""))
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return {"invoice_number": f"{prefix}{next_num:03d}"}


@router.get("", response_model=list[InvoiceResponse])
async def list_invoices(
    client_id: int | None = Query(None),
    status: InvoiceStatus | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List all invoices with optional filtering."""
    q = db.query(Invoice)

    if client_id:
        q = q.filter(Invoice.client_id == client_id)

    if status:
        q = q.filter(Invoice.status == status.value)

    if start_date:
        q = q.filter(Invoice.invoice_date >= start_date)

    if end_date:
        q = q.filter(Invoice.invoice_date <= end_date)

    q = q.order_by(Invoice.invoice_date.desc())
    return q.offset(offset).limit(limit).all()


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Get a specific invoice with items."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.post("", response_model=InvoiceResponse)
async def create_invoice(invoice: InvoiceCreate, db: Session = Depends(get_db)):
    """Create a new invoice with items."""
    # Verify client exists
    client = db.query(Client).filter(Client.id == invoice.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Create invoice
    db_invoice = Invoice(
        client_id=invoice.client_id,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        notes=invoice.notes,
        status=InvoiceStatus.DRAFT.value,
    )
    db.add(db_invoice)
    db.flush()

    # Create invoice items and calculate totals
    subtotal = Decimal("0")
    vat_total = Decimal("0")

    for item in invoice.items:
        line_total = item.quantity * item.unit_price
        vat_amount = line_total * (item.vat_rate / 100)

        db_item = InvoiceItem(
            invoice_id=db_invoice.id,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
            vat_rate=item.vat_rate,
            line_total=line_total,
        )
        db.add(db_item)

        subtotal += line_total
        vat_total += vat_amount

    # Update invoice totals
    db_invoice.subtotal = subtotal
    db_invoice.vat_amount = vat_total
    db_invoice.total_amount = subtotal + vat_total

    db.commit()
    db.refresh(db_invoice)
    logger.info(f"Created invoice: {db_invoice.invoice_number} (ID: {db_invoice.id})")
    return db_invoice


@router.put("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: int, invoice: InvoiceUpdate, db: Session = Depends(get_db)
):
    """Update an existing invoice, including line items if provided."""
    db_invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not db_invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    update_data = invoice.model_dump(exclude_unset=True)
    items_data = update_data.pop("items", None)

    # Update scalar fields
    if "status" in update_data:
        update_data["status"] = update_data["status"].value

    for field, value in update_data.items():
        setattr(db_invoice, field, value)

    # Update items if provided
    if items_data is not None:
        # Delete existing items
        db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).delete()

        # Create new items and recalculate totals
        subtotal = Decimal("0")
        vat_total = Decimal("0")

        for item_data in items_data:
            qty = Decimal(str(item_data["quantity"]))
            price = Decimal(str(item_data["unit_price"]))
            vat_rate = Decimal(str(item_data["vat_rate"]))
            line_total = qty * price
            vat_amount = line_total * (vat_rate / 100)

            db_item = InvoiceItem(
                invoice_id=invoice_id,
                description=item_data["description"],
                quantity=qty,
                unit_price=price,
                vat_rate=vat_rate,
                line_total=line_total,
            )
            db.add(db_item)

            subtotal += line_total
            vat_total += vat_amount

        db_invoice.subtotal = subtotal
        db_invoice.vat_amount = vat_total
        db_invoice.total_amount = subtotal + vat_total

    db.commit()
    db.refresh(db_invoice)
    return db_invoice


@router.delete("/{invoice_id}")
async def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Delete an invoice."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    db.delete(invoice)
    db.commit()
    return {"status": "deleted", "id": invoice_id}


@router.post("/{invoice_id}/send")
async def send_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Mark an invoice as sent."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status != InvoiceStatus.DRAFT.value:
        raise HTTPException(status_code=400, detail="Only draft invoices can be sent")

    invoice.status = InvoiceStatus.SENT.value
    db.commit()
    return {"status": "sent", "id": invoice_id}


@router.post("/{invoice_id}/mark-paid")
async def mark_invoice_paid(invoice_id: int, db: Session = Depends(get_db)):
    """Mark an invoice as paid."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice.status = InvoiceStatus.PAID.value
    db.commit()
    return {"status": "paid", "id": invoice_id}


@router.get("/{invoice_id}/pdf")
async def download_invoice_pdf(invoice_id: int, db: Session = Depends(get_db)):
    """Generate and download an invoice as PDF."""
    import base64
    import tempfile

    from fpdf import FPDF

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    client = db.query(Client).filter(Client.id == invoice.client_id).first()

    # Load company settings
    from ..models import CompanySettings

    company = db.query(CompanySettings).first()

    def fmt_date(d):
        return d.strftime("%d-%m-%Y") if d else ""

    def fmt_amount(amount):
        return f"EUR {amount:,.2f}"

    pdf = FPDF()

    # Register custom fonts
    fonts_dir = str(
        __import__("pathlib").Path(__file__).resolve().parent.parent / "fonts"
    )
    pdf.add_font("SpaceGrotesk", "", f"{fonts_dir}/SpaceGrotesk-Regular.ttf")
    pdf.add_font("SpaceGrotesk", "B", f"{fonts_dir}/SpaceGrotesk-Bold.ttf")
    pdf.add_font("JetBrainsMono", "", f"{fonts_dir}/JetBrainsMono-Regular.ttf")
    pdf.add_font("JetBrainsMono", "B", f"{fonts_dir}/JetBrainsMono-Bold.ttf")

    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    logo_tmpfile = None

    # --- Company Header (left side) ---
    header_start_y = pdf.get_y()
    logo_h = 0

    if company and company.logo_base64:
        try:
            # Parse data URI: data:image/png;base64,<data>
            data_uri = company.logo_base64
            header, b64data = data_uri.split(",", 1)
            mime = header.split(":")[1].split(";")[0]
            ext_map = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
                "image/svg+xml": ".svg",
            }
            ext = ext_map.get(mime, ".png")
            img_bytes = base64.b64decode(b64data)
            logo_tmpfile = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            logo_tmpfile.write(img_bytes)
            logo_tmpfile.flush()
            pdf.image(logo_tmpfile.name, x=10, y=10, h=18)
            logo_h = 22
        except Exception:
            logo_h = 0

    company_y = 10 + logo_h
    pdf.set_y(company_y)

    if company and company.name:
        pdf.set_font("SpaceGrotesk", "B", 13)
        pdf.set_text_color(17, 24, 39)
        pdf.cell(95, 6, company.name, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("SpaceGrotesk", "", 9)
        pdf.set_text_color(107, 114, 128)
        if company.address:
            pdf.cell(95, 4.5, company.address, new_x="LMARGIN", new_y="NEXT")
        loc = ", ".join(filter(None, [company.postal_code, company.city]))
        if loc:
            pdf.cell(95, 4.5, loc, new_x="LMARGIN", new_y="NEXT")
        if company.country:
            pdf.cell(95, 4.5, company.country, new_x="LMARGIN", new_y="NEXT")
        if company.vat_number:
            pdf.cell(95, 4.5, f"VAT: {company.vat_number}", new_x="LMARGIN", new_y="NEXT")
        if company.chamber_of_commerce:
            pdf.cell(95, 4.5, f"KvK: {company.chamber_of_commerce}", new_x="LMARGIN", new_y="NEXT")
        if company.email:
            pdf.cell(95, 4.5, company.email, new_x="LMARGIN", new_y="NEXT")
        if company.phone:
            pdf.cell(95, 4.5, company.phone, new_x="LMARGIN", new_y="NEXT")

    # Track where company info ends
    company_end_y = pdf.get_y()

    # --- Invoice title + meta (right side) ---
    pdf.set_y(10)
    pdf.set_font("SpaceGrotesk", "B", 28)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(0, 14, "INVOICE", align="R", new_x="LMARGIN", new_y="NEXT")

    meta_y = 26
    pdf.set_y(meta_y)
    pdf.set_font("SpaceGrotesk", "", 10)
    pdf.set_text_color(107, 114, 128)
    pdf.cell(120)
    pdf.cell(30, 6, "Invoice #", align="R")
    pdf.set_font("JetBrainsMono", "B", 10)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(40, 6, invoice.invoice_number, align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("SpaceGrotesk", "", 10)
    pdf.set_text_color(107, 114, 128)
    pdf.cell(120)
    pdf.cell(30, 6, "Date", align="R")
    pdf.set_font("JetBrainsMono", "", 10)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(40, 6, fmt_date(invoice.invoice_date), align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("SpaceGrotesk", "", 10)
    pdf.set_text_color(107, 114, 128)
    pdf.cell(120)
    pdf.cell(30, 6, "Due Date", align="R")
    pdf.set_font("JetBrainsMono", "", 10)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(40, 6, fmt_date(invoice.due_date), align="R", new_x="LMARGIN", new_y="NEXT")

    # Status badge
    status_colors = {
        "draft": (107, 114, 128),
        "sent": (59, 130, 246),
        "paid": (34, 197, 94),
        "overdue": (239, 68, 68),
        "cancelled": (156, 163, 175),
    }
    sr, sg, sb = status_colors.get(invoice.status, (107, 114, 128))
    pdf.set_font("SpaceGrotesk", "B", 9)
    status_w = pdf.get_string_width(invoice.status.upper()) + 8
    pdf.set_fill_color(sr, sg, sb)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(120)
    right_edge = pdf.w - pdf.r_margin
    pdf.set_x(right_edge - status_w)
    pdf.cell(status_w, 7, invoice.status.upper(), fill=True, new_x="LMARGIN", new_y="NEXT")

    # Move below whichever column is taller (company info vs invoice meta)
    right_end_y = pdf.get_y()
    pdf.set_y(max(right_end_y, company_end_y) + 8)

    # Separator
    pdf.set_draw_color(229, 231, 235)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)

    # --- Bill To ---
    pdf.set_font("SpaceGrotesk", "B", 8)
    pdf.set_text_color(107, 114, 128)
    pdf.cell(0, 5, "BILL TO", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if client:
        x = pdf.get_x()
        y = pdf.get_y()
        pdf.set_draw_color(59, 130, 246)
        pdf.set_line_width(0.8)
        pdf.line(x, y, x, y + 30)
        pdf.set_line_width(0.2)

        pdf.set_x(x + 4)
        pdf.set_font("SpaceGrotesk", "B", 11)
        pdf.set_text_color(17, 24, 39)
        pdf.cell(0, 6, client.name, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("SpaceGrotesk", "", 10)
        pdf.set_text_color(55, 65, 81)
        if client.address:
            pdf.set_x(x + 4)
            pdf.cell(0, 5, client.address, new_x="LMARGIN", new_y="NEXT")
        location = ", ".join(filter(None, [client.postal_code, client.city]))
        if location:
            pdf.set_x(x + 4)
            pdf.cell(0, 5, location, new_x="LMARGIN", new_y="NEXT")
        if client.country:
            pdf.set_x(x + 4)
            pdf.cell(0, 5, client.country, new_x="LMARGIN", new_y="NEXT")
        if client.vat_number:
            pdf.set_x(x + 4)
            pdf.set_font("SpaceGrotesk", "", 10)
            pdf.set_text_color(107, 114, 128)
            pdf.cell(15, 5, "VAT: ")
            pdf.set_font("JetBrainsMono", "", 9)
            pdf.set_text_color(55, 65, 81)
            pdf.cell(0, 5, client.vat_number, new_x="LMARGIN", new_y="NEXT")
        if client.chamber_of_commerce:
            pdf.set_x(x + 4)
            pdf.set_font("SpaceGrotesk", "", 10)
            pdf.set_text_color(107, 114, 128)
            pdf.cell(15, 5, "KvK: ")
            pdf.set_font("JetBrainsMono", "", 9)
            pdf.set_text_color(55, 65, 81)
            pdf.cell(0, 5, client.chamber_of_commerce, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)

    # --- Items Table ---
    col_widths = [75, 20, 30, 20, 35]
    headers = ["Description", "Qty", "Unit Price", "VAT %", "Total"]

    pdf.set_fill_color(243, 244, 246)
    pdf.set_font("SpaceGrotesk", "B", 8)
    pdf.set_text_color(107, 114, 128)
    for i, (header, w) in enumerate(zip(headers, col_widths)):
        align = "L" if i == 0 else "R" if i in [2, 4] else "C"
        pdf.cell(w, 8, header, fill=True, align=align)
    pdf.ln()

    pdf.set_draw_color(209, 213, 219)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + sum(col_widths), pdf.get_y())
    pdf.set_line_width(0.2)

    pdf.set_font("SpaceGrotesk", "", 10)
    pdf.set_text_color(31, 41, 55)
    line_height = 5
    for item in invoice.items:
        pdf.set_draw_color(229, 231, 235)
        x_start = pdf.get_x()
        y_start = pdf.get_y()

        # Render description with multi_cell to support wrapping
        pdf.multi_cell(col_widths[0], line_height, str(item.description), align="L", new_x="RIGHT", new_y="TOP", max_line_height=line_height)
        desc_bottom = pdf.get_y()
        row_height = max(desc_bottom - y_start, 9)

        # Render remaining columns vertically centered in the row
        pdf.set_xy(x_start + col_widths[0], y_start)
        pdf.set_font("JetBrainsMono", "", 9)
        pdf.cell(col_widths[1], row_height, str(item.quantity), align="C")
        pdf.cell(col_widths[2], row_height, fmt_amount(item.unit_price), align="R")
        pdf.cell(col_widths[3], row_height, f"{item.vat_rate}%", align="C")
        pdf.cell(col_widths[4], row_height, fmt_amount(item.line_total), align="R")
        pdf.set_font("SpaceGrotesk", "", 10)
        pdf.set_y(y_start + row_height)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + sum(col_widths), pdf.get_y())

    pdf.ln(8)

    # --- Totals ---
    value_w = 50
    label_w = 40
    totals_x = pdf.l_margin + sum(col_widths) - label_w - value_w

    pdf.set_font("SpaceGrotesk", "", 10)
    pdf.set_text_color(107, 114, 128)
    pdf.set_x(totals_x)
    pdf.cell(label_w, 7, "Subtotal", align="R")
    pdf.set_font("JetBrainsMono", "", 10)
    pdf.set_text_color(31, 41, 55)
    pdf.cell(value_w, 7, fmt_amount(invoice.subtotal), align="R")
    pdf.ln()

    pdf.set_font("SpaceGrotesk", "", 10)
    pdf.set_text_color(107, 114, 128)
    pdf.set_x(totals_x)
    pdf.cell(label_w, 7, "VAT", align="R")
    pdf.set_font("JetBrainsMono", "", 10)
    pdf.set_text_color(31, 41, 55)
    pdf.cell(value_w, 7, fmt_amount(invoice.vat_amount), align="R")
    pdf.ln()

    pdf.set_draw_color(31, 41, 55)
    pdf.set_line_width(0.5)
    y = pdf.get_y()
    pdf.line(totals_x, y, totals_x + label_w + value_w, y)
    pdf.set_line_width(0.2)
    pdf.ln(2)

    pdf.set_font("SpaceGrotesk", "B", 13)
    pdf.set_text_color(17, 24, 39)
    pdf.set_x(totals_x)
    pdf.cell(label_w, 9, "Total", align="R")
    pdf.set_font("JetBrainsMono", "B", 13)
    pdf.cell(value_w, 9, fmt_amount(invoice.total_amount), align="R")
    pdf.ln()

    # --- Notes ---
    if invoice.notes:
        pdf.ln(10)
        pdf.set_font("SpaceGrotesk", "B", 8)
        pdf.set_text_color(107, 114, 128)
        pdf.cell(0, 5, "NOTES", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("SpaceGrotesk", "", 10)
        pdf.set_text_color(55, 65, 81)
        pdf.multi_cell(0, 5, invoice.notes)

    # --- Payment Details Footer ---
    if company and (company.iban or company.bank_name):
        pdf.ln(10)
        pdf.set_draw_color(229, 231, 235)
        pdf.set_line_width(0.3)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(4)
        pdf.set_font("SpaceGrotesk", "B", 8)
        pdf.set_text_color(107, 114, 128)
        pdf.cell(0, 5, "PAYMENT DETAILS", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("SpaceGrotesk", "", 10)
        pdf.set_text_color(55, 65, 81)
        if company.iban:
            pdf.cell(20, 5, "IBAN: ")
            pdf.set_font("JetBrainsMono", "B", 10)
            pdf.cell(0, 5, company.iban, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("SpaceGrotesk", "", 10)
        if company.bank_name:
            pdf.cell(20, 5, "Bank: ")
            pdf.cell(0, 5, company.bank_name, new_x="LMARGIN", new_y="NEXT")

    # Output PDF
    pdf_bytes = pdf.output()
    pdf_buffer = io.BytesIO(pdf_bytes)
    filename = f"{invoice.invoice_number}.pdf"

    # Clean up temp logo file
    if logo_tmpfile:
        import os

        try:
            os.unlink(logo_tmpfile.name)
        except OSError:
            pass

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
