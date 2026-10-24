// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "CognisCompanion",
    platforms: [.macOS(.v15)],
    products: [.executable(name: "CognisCompanion", targets: ["CognisCompanion"])],
    dependencies: [.package(url: "https://github.com/sparkle-project/Sparkle", exact: "2.9.3")],
    targets: [
        .target(name: "CompanionContract"),
        .executableTarget(name: "CognisCompanion", dependencies: [
            "CompanionContract", .product(name: "Sparkle", package: "Sparkle")
        ], linkerSettings: [.unsafeFlags(["-Xlinker", "-rpath", "-Xlinker", "@executable_path/../Frameworks"])]),
        .testTarget(name: "CompanionContractTests", dependencies: ["CompanionContract"]),
        .testTarget(name: "CompanionWebKitTests", dependencies: ["CognisCompanion", "CompanionContract"])
    ]
)
