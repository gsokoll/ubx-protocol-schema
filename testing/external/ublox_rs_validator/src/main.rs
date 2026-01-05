use std::io::{self, Read};
use ublox::{Parser, PacketRef};
use serde::Serialize;

#[derive(Serialize)]
struct ParseResult {
    parsed: bool,
    message_class: Option<u8>,
    message_id: Option<u8>,
    payload_len: Option<usize>,
    error: Option<String>,
}

fn main() {
    let mut input = Vec::new();
    
    // Check for hex input from command line or stdin
    let args: Vec<String> = std::env::args().collect();
    
    if args.len() > 1 {
        // Hex string provided as argument
        match hex::decode(&args[1]) {
            Ok(bytes) => input = bytes,
            Err(e) => {
                let result = ParseResult {
                    parsed: false,
                    message_class: None,
                    message_id: None,
                    payload_len: None,
                    error: Some(format!("Invalid hex: {}", e)),
                };
                println!("{}", serde_json::to_string(&result).unwrap());
                return;
            }
        }
    } else {
        // Read from stdin
        io::stdin().read_to_end(&mut input).unwrap();
    }
    
    let mut parser = Parser::default();
    let mut result = ParseResult {
        parsed: false,
        message_class: None,
        message_id: None,
        payload_len: None,
        error: None,
    };
    
    let mut it = parser.consume(&input);
    
    match it.next() {
        Some(Ok(packet)) => {
            match packet {
                PacketRef::NavPvt(msg) => {
                    result.parsed = true;
                    result.message_class = Some(0x01);
                    result.message_id = Some(0x07);
                    result.payload_len = Some(92);
                }
                PacketRef::NavPosLlh(msg) => {
                    result.parsed = true;
                    result.message_class = Some(0x01);
                    result.message_id = Some(0x02);
                    result.payload_len = Some(28);
                }
                PacketRef::NavStatus(msg) => {
                    result.parsed = true;
                    result.message_class = Some(0x01);
                    result.message_id = Some(0x03);
                    result.payload_len = Some(16);
                }
                PacketRef::AckAck(msg) => {
                    result.parsed = true;
                    result.message_class = Some(0x05);
                    result.message_id = Some(0x01);
                    result.payload_len = Some(2);
                }
                PacketRef::AckNak(msg) => {
                    result.parsed = true;
                    result.message_class = Some(0x05);
                    result.message_id = Some(0x00);
                    result.payload_len = Some(2);
                }
                _ => {
                    result.parsed = true;
                    result.error = Some("Parsed but type not explicitly handled".to_string());
                }
            }
        }
        Some(Err(e)) => {
            result.error = Some(format!("Parse error: {:?}", e));
        }
        None => {
            result.error = Some("No packet found in input".to_string());
        }
    }
    
    println!("{}", serde_json::to_string(&result).unwrap());
}
