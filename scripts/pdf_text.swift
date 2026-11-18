// Read-only PDF text extraction for the local source-verification audit.
import Foundation
import PDFKit

let args = CommandLine.arguments
guard args.count == 3, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    fputs("usage: pdf_text /absolute/input.pdf /absolute/output.json\n", stderr)
    exit(1)
}
var pages: [[String: Any]] = []
for index in 0..<doc.pageCount {
    let text = doc.page(at: index)?.string ?? ""
    pages.append(["pdf_page": index + 1, "text": text])
}
let data = try JSONSerialization.data(withJSONObject: pages)
try data.write(to: URL(fileURLWithPath: args[2]))
print("pages \(doc.pageCount)")
