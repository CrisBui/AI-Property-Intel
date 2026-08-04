package com.propertyintel.controller;

import com.propertyintel.dto.response.ListingDetailResponse;
import com.propertyintel.service.ListingService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/listings")
@RequiredArgsConstructor
public class ListingController {
    private final ListingService listingService;

    @GetMapping("/{sourceId}")
    public ResponseEntity<ListingDetailResponse> searchListing(@PathVariable String sourceId) {
        ListingDetailResponse detail = listingService.getListingDetail(sourceId);
        return ResponseEntity.ok(detail);

    }
}
