use rstk::*;
use std::{thread, time::Duration};
use sysinfo::{Disks, System};

fn main() {
    let root = start_wish().expect("failed to start wish/tk");

    // Set window title (HOW THE FUCK DID THIS TAKE YOU AN HOUR)
    rstk::tell_wish(&format!("wm title {} \"Vanilla Look\"", root.id()));

    let title = make_label(&root);
    title.text("Vanilla LOOK v0.1");
    title.grid().layout();

    // CPU
    let cpu_label = make_label(&root);
    cpu_label.text("CPU: fetching...");
    cpu_label.grid().layout();
    let cpu_bar = make_progressbar(&root, Orientation::Horizontal, ProgressMode::Determinate);
    cpu_bar.maximum(100.0);
    cpu_bar.length(500);
    cpu_bar.grid().layout();

    // Memory
    let mem_label = make_label(&root);
    mem_label.text("Memory: fetching...");
    mem_label.grid().layout();
    let mem_bar = make_progressbar(&root, Orientation::Horizontal, ProgressMode::Determinate);
    mem_bar.maximum(100.0);
    mem_bar.length(500);
    mem_bar.grid().layout();

    // Disk
    let disk_label = make_label(&root);
    disk_label.text("Disk: fetching...");
    disk_label.grid().layout();
    let disk_bar = make_progressbar(&root, Orientation::Horizontal, ProgressMode::Determinate);
    disk_bar.maximum(100.0);
    disk_bar.length(500);
    disk_bar.grid().layout();

    let note = make_label(&root);
    note.text("Updates every 1s, close window to exit.");
    note.grid().layout();

    // Clone widgets for thread
    let cpu_label_c = cpu_label.clone();
    let cpu_bar_c = cpu_bar.clone();
    let mem_label_c = mem_label.clone();
    let mem_bar_c = mem_bar.clone();
    let disk_label_c = disk_label.clone();
    let disk_bar_c = disk_bar.clone();

    thread::spawn(move || {
        let mut sys = System::new_all();
        loop {
            sys.refresh_all();
            let disks = Disks::new_with_refreshed_list();

            // CPU (average)
            let cpus = sys.cpus();
            let cpu_usage: f32 = if !cpus.is_empty() {
                let sum: f32 = cpus.iter().map(|c| c.cpu_usage()).sum();
                sum / (cpus.len() as f32)
            } else {
                0.0
            };

            // Memory
            let total_mem = sys.total_memory() as f32;
            let used_mem = sys.used_memory() as f32;
            let mem_percent = if total_mem > 0.0 {
                used_mem / total_mem * 100.0
            } else {
                0.0
            };

            // Disk
            let mut total_bytes: u128 = 0;
            let mut used_bytes: u128 = 0;
            for d in &disks {
                let t = d.total_space() as u128;
                let avail = d.available_space() as u128;
                total_bytes += t;
                used_bytes += t.saturating_sub(avail);
            }
            let disk_percent =
                if total_bytes > 0 { (used_bytes as f64 / total_bytes as f64) * 100.0 } else { 0.0 };

            cpu_label_c.text(&format!("CPU: {:.1}%", cpu_usage));
            cpu_bar_c.value(cpu_usage as f64);

            mem_label_c.text(&format!(
                "Memory: {:.0} MB / {:.0} MB ({:.1}%)",
                used_mem / 1024.0,
                total_mem / 1024.0,
                mem_percent
            ));
            mem_bar_c.value(mem_percent as f64);

            let disk_text = if total_bytes > 0 {
                format!(
                    "Disk: {:.2} GB / {:.2} GB ({:.1}%)",
                    used_bytes as f64 / 1e9,
                    total_bytes as f64 / 1e9,
                    disk_percent
                )
            } else {
                "Disk: no disks found".to_string()
            };
            disk_label_c.text(&disk_text);
            disk_bar_c.value(disk_percent);

            thread::sleep(Duration::from_secs(1));
        }
    });

    mainloop();
}