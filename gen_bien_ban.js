const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, BorderStyle, WidthType, UnderlineType,
  PageOrientation, HeadingLevel
} = require('docx');
const fs = require('fs');

const data = JSON.parse(process.argv[2]);

const {
  tenKhoa = '',
  tenDeTai = '',
  sinhVien = '',
  maSV = '',
  nhanXetCT = '',
  nhanXetTV = '',
  yeuCauChinhSua = '',
  chuTichHD = '',
  thuKy = '',
  chuTichSauChinhSua = '',
  ngay = '',
  thang = '',
  nam = '',
  ngay2 = '',
  thang2 = '',
  nam2 = '',
  khoaHoc = '',
} = data;

const noBorder = {
  top: { style: BorderStyle.NONE, size: 0 },
  bottom: { style: BorderStyle.NONE, size: 0 },
  left: { style: BorderStyle.NONE, size: 0 },
  right: { style: BorderStyle.NONE, size: 0 },
};

const thinBorder = {
  top: { style: BorderStyle.SINGLE, size: 1, color: '000000' },
  bottom: { style: BorderStyle.SINGLE, size: 1, color: '000000' },
  left: { style: BorderStyle.SINGLE, size: 1, color: '000000' },
  right: { style: BorderStyle.SINGLE, size: 1, color: '000000' },
};

function txt(text, opts = {}) {
  return new TextRun({ text, font: 'Times New Roman', size: 24, ...opts });
}

function boldTxt(text, opts = {}) {
  return txt(text, { bold: true, ...opts });
}

function centerPara(children, spacing = {}) {
  return new Paragraph({ alignment: AlignmentType.CENTER, children, spacing: { before: 0, after: 0, ...spacing } });
}

function leftPara(children, spacing = {}) {
  return new Paragraph({ alignment: AlignmentType.LEFT, children, spacing: { before: 0, after: 0, ...spacing } });
}

function dottedLinePara(label = '', value = '', indent = 0) {
  const dots = '....................................................................................................'.repeat(2);
  return leftPara([
    txt(label),
    txt(value || dots.substring(0, Math.max(10, 80 - label.length)), { underline: value ? { type: UnderlineType.SINGLE } : undefined }),
  ]);
}

function dotLine(count = 100) {
  return '.'.repeat(count);
}

function signatureTable(leftLabel, leftName, rightLabel, rightName) {
  return new Table({
    width: { size: 9026, type: WidthType.DXA },
    columnWidths: [4513, 4513],
    borders: {
      top: { style: BorderStyle.NONE },
      bottom: { style: BorderStyle.NONE },
      left: { style: BorderStyle.NONE },
      right: { style: BorderStyle.NONE },
      insideH: { style: BorderStyle.NONE },
      insideV: { style: BorderStyle.NONE },
    },
    rows: [
      new TableRow({
        children: [
          new TableCell({
            borders: noBorder,
            width: { size: 4513, type: WidthType.DXA },
            children: [centerPara([boldTxt(leftLabel)])],
          }),
          new TableCell({
            borders: noBorder,
            width: { size: 4513, type: WidthType.DXA },
            children: [centerPara([boldTxt(rightLabel)])],
          }),
        ],
      }),
      new TableRow({
        children: [
          new TableCell({
            borders: noBorder,
            width: { size: 4513, type: WidthType.DXA },
            children: [centerPara([txt('(Ký, họ và tên)')])],
          }),
          new TableCell({
            borders: noBorder,
            width: { size: 4513, type: WidthType.DXA },
            children: [centerPara([txt('(Ký, họ và tên)')])],
          }),
        ],
      }),
      new TableRow({
        children: [
          new TableCell({
            borders: noBorder,
            width: { size: 4513, type: WidthType.DXA },
            children: [
              new Paragraph({ spacing: { before: 800, after: 0 } }),
              centerPara([boldTxt(leftName || '')]),
            ],
          }),
          new TableCell({
            borders: noBorder,
            width: { size: 4513, type: WidthType.DXA },
            children: [
              new Paragraph({ spacing: { before: 800, after: 0 } }),
              centerPara([boldTxt(rightName || '')]),
            ],
          }),
        ],
      }),
    ],
  });
}

function multilineContent(text, emptyLines = 5) {
  const lines = text ? text.split('\n') : [];
  const paras = [];
  if (lines.length > 0) {
    for (const line of lines) {
      paras.push(leftPara([txt(line)]));
    }
  } else {
    for (let i = 0; i < emptyLines; i++) {
      paras.push(leftPara([txt(dotLine(90))]));
    }
  }
  return paras;
}

const doc = new Document({
  styles: {
    default: {
      document: { run: { font: 'Times New Roman', size: 24 } },
    },
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 11906, height: 16838 }, // A4
          margin: { top: 1134, right: 851, bottom: 1134, left: 1701 }, // ~2cm left, ~1.5cm others (in DXA: 567 per cm)
        },
      },
      children: [
        // Header
        centerPara([boldTxt('Đại học Công nghệ Kỹ thuật TP.HCM')]),
        centerPara([boldTxt('KHOA KINH TẾ')]),
        centerPara([boldTxt(`NGÀNH ${tenKhoa.toUpperCase() || 'KINH DOANH QUỐC TẾ'}`)]),

        // Divider line
        new Paragraph({
          spacing: { before: 80, after: 80 },
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: '000000', space: 1 } },
          children: [txt('')],
        }),

        new Paragraph({ spacing: { before: 120, after: 0 } }),

        // Title
        centerPara([boldTxt('BIÊN BẢN HỌP HỘI ĐỒNG ĐÁNH GIÁ KHÓA LUẬN TỐT NGHIỆP')], { before: 100 }),
        centerPara([boldTxt(`NGÀNH ${tenKhoa.toUpperCase() || 'KINH DOANH QUỐC TẾ'} KHÓA ${khoaHoc || '....'}`)], { before: 40, after: 160 }),

        // Section 1
        leftPara([boldTxt('1. Thông tin chung')], { before: 80, after: 80 }),

        leftPara([txt('Tên khóa luận: '), txt(tenDeTai || dotLine(70), { underline: tenDeTai ? { type: UnderlineType.SINGLE } : undefined })]),
        new Paragraph({ spacing: { before: 0, after: 0 } }),
        leftPara([txt(dotLine(90))]),
        new Paragraph({ spacing: { before: 0, after: 0 } }),

        leftPara([txt('Sinh viên thực hiện: '), txt(sinhVien || dotLine(50))], { before: 80 }),

        leftPara([txt('MSSV: '), txt(maSV || dotLine(70))], { before: 80 }),

        // Section 2
        leftPara([boldTxt('2. Nhận xét của các thành viên hội đồng:')], { before: 160, after: 80 }),

        leftPara([boldTxt('Nhận xét của Chủ tịch hội đồng:')], { before: 80, after: 40 }),
        ...multilineContent(nhanXetCT, 4),

        leftPara([boldTxt('Nhận xét của Thành viên hội đồng:')], { before: 120, after: 40 }),
        ...multilineContent(nhanXetTV, 4),

        // Section 3
        leftPara([boldTxt('3. Yêu cầu chỉnh sửa')], { before: 160, after: 80 }),
        ...multilineContent(yeuCauChinhSua, 5),

        // Date line
        new Paragraph({ spacing: { before: 160, after: 0 } }),
        new Table({
          width: { size: 9026, type: WidthType.DXA },
          columnWidths: [4513, 4513],
          borders: {
            top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE },
            left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
            insideH: { style: BorderStyle.NONE }, insideV: { style: BorderStyle.NONE },
          },
          rows: [
            new TableRow({
              children: [
                new TableCell({
                  borders: noBorder,
                  width: { size: 4513, type: WidthType.DXA },
                  children: [leftPara([txt('')])],
                }),
                new TableCell({
                  borders: noBorder,
                  width: { size: 4513, type: WidthType.DXA },
                  children: [centerPara([
                    txt(`Ngày ${ngay || '.....'} tháng ${thang || '.....'} năm ${nam || '.....'}`)
                  ])],
                }),
              ],
            }),
          ],
        }),

        // Signatures
        new Paragraph({ spacing: { before: 80, after: 0 } }),
        signatureTable('Chủ tịch hội đồng', chuTichHD, 'Thư ký', thuKy),

        // Section 4 - After revision
        new Paragraph({ spacing: { before: 240, after: 0 } }),
        new Paragraph({
          spacing: { before: 80, after: 80 },
          border: { top: { style: BorderStyle.SINGLE, size: 6, color: '000000', space: 1 } },
          children: [txt('')],
        }),

        centerPara([boldTxt('Ý KIẾN CỦA CHỦ TỊCH HỘI ĐỒNG SAU KHI SINH VIÊN CHỈNH SỬA')], { before: 80, after: 80 }),

        ...multilineContent(null, 5),

        new Paragraph({ spacing: { before: 120, after: 0 } }),
        new Table({
          width: { size: 9026, type: WidthType.DXA },
          columnWidths: [4513, 4513],
          borders: {
            top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE },
            left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
            insideH: { style: BorderStyle.NONE }, insideV: { style: BorderStyle.NONE },
          },
          rows: [
            new TableRow({
              children: [
                new TableCell({
                  borders: noBorder,
                  width: { size: 4513, type: WidthType.DXA },
                  children: [leftPara([txt('')])],
                }),
                new TableCell({
                  borders: noBorder,
                  width: { size: 4513, type: WidthType.DXA },
                  children: [centerPara([
                    txt(`Ngày ${ngay2 || '.....'} tháng ${thang2 || '.....'} năm ${nam2 || '.....'}`)
                  ])],
                }),
              ],
            }),
          ],
        }),
        new Paragraph({ spacing: { before: 80, after: 0 } }),
        new Table({
          width: { size: 9026, type: WidthType.DXA },
          columnWidths: [9026],
          borders: {
            top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE },
            left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
            insideH: { style: BorderStyle.NONE }, insideV: { style: BorderStyle.NONE },
          },
          rows: [
            new TableRow({
              children: [
                new TableCell({
                  borders: noBorder,
                  width: { size: 9026, type: WidthType.DXA },
                  children: [centerPara([boldTxt('Chủ tịch hội đồng')])],
                }),
              ],
            }),
            new TableRow({
              children: [
                new TableCell({
                  borders: noBorder,
                  width: { size: 9026, type: WidthType.DXA },
                  children: [centerPara([txt('(Ký, họ và tên)')])],
                }),
              ],
            }),
            new TableRow({
              children: [
                new TableCell({
                  borders: noBorder,
                  width: { size: 9026, type: WidthType.DXA },
                  children: [
                    new Paragraph({ spacing: { before: 800, after: 0 } }),
                    centerPara([boldTxt(chuTichSauChinhSua || chuTichHD || '')]),
                  ],
                }),
              ],
            }),
          ],
        }),
      ],
    },
  ],
});

Packer.toBuffer(doc).then(buf => {
  const outPath = process.argv[3] || '/tmp/bien_ban.docx';
  fs.writeFileSync(outPath, buf);
  console.log('OK:' + outPath);
}).catch(err => {
  console.error('ERR:' + err.message);
  process.exit(1);
});
