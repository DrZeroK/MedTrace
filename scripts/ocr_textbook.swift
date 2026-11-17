// Local scanned-PDF extraction. Original PDF is read-only; page records are retained.
import Foundation
import PDFKit
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count == 3, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    fputs("usage: ocr_textbook /absolute/input.pdf /absolute/output-directory\n", stderr)
    exit(1)
}
let output = URL(fileURLWithPath: args[2], isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
for index in 0..<doc.pageCount {
    let target = output.appendingPathComponent(String(format: "%04d.json", index + 1))
    if FileManager.default.fileExists(atPath: target.path) { continue }
    try autoreleasepool {
        guard let page = doc.page(at: index) else { throw NSError(domain: "MissingPage", code: index) }
        let bounds = page.bounds(for: .mediaBox)
        let size = NSSize(width: 1800, height: 1800 * bounds.height / bounds.width)
        let image = page.thumbnail(of: size, for: .mediaBox)
        guard let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            throw NSError(domain: "RenderFailed", code: index)
        }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["zh-Hans", "en-US"]
        request.usesLanguageCorrection = true
        try VNImageRequestHandler(cgImage: cg).perform([request])
        let observations = (request.results ?? []).sorted {
            if abs($0.boundingBox.midY - $1.boundingBox.midY) > 0.008 {
                return $0.boundingBox.midY > $1.boundingBox.midY
            }
            return $0.boundingBox.minX < $1.boundingBox.minX
        }
        let lines = observations.compactMap { $0.topCandidates(1).first }
        let record: [String: Any] = ["pdf_page": index + 1, "text": lines.map { $0.string }.joined(separator: "\n"),
                                   "method": "Apple Vision accurate zh-Hans/en-US",
                                   "mean_confidence": lines.isEmpty ? 0 : lines.reduce(0.0) { $0 + Double($1.confidence) } / Double(lines.count)]
        try JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]).write(to: target)
    }
    if (index + 1) % 10 == 0 { print("OCR \(index + 1)/\(doc.pageCount)"); fflush(stdout) }
}
